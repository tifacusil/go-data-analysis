"""
gRPC servicer — server-to-server transport only.
The frontend never calls this; it uses the FastAPI HTTP server instead.
"""
import json
import logging

import grpc

from app.generated import analysis_pb2, analysis_pb2_grpc
from app import cache
from app.config import Config
from services import outliers_service, denoise_service, regression_service, predict_service

logger = logging.getLogger("grpc_servicer")

_OUTLIERS_METHODS = {"3sigma", "chauvenet", "iqr"}
_DENOISE_METHODS = {"wavelet", "emd", "svm"}
_REGRESSION_MODELS = {"polynomial", "bayesian"}
_PREDICT_MODELS = {"arima", "gm11"}


def _invalid(context: grpc.ServicerContext, msg: str):
    context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
    context.set_details(msg)


class AnalysisServicer(analysis_pb2_grpc.AnalysisServiceServicer):

    def DetectOutliers(self, request, context):
        if request.method not in _OUTLIERS_METHODS:
            _invalid(context, f"method must be one of {sorted(_OUTLIERS_METHODS)}")
            return analysis_pb2.OutliersResponse()
        if not request.values:
            _invalid(context, "values must not be empty")
            return analysis_pb2.OutliersResponse()

        body = {"values": list(request.values), "timestamps": list(request.timestamps), "method": request.method}
        key = cache.make_key(body)
        cached = cache.get(key)
        if cached:
            return _dict_to_outliers_response(cached)

        try:
            result = outliers_service.detect_outliers(list(request.values), list(request.timestamps), request.method)
        except ValueError as exc:
            _invalid(context, str(exc))
            return analysis_pb2.OutliersResponse()

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return _dict_to_outliers_response(result)

    def Denoise(self, request, context):
        if request.method not in _DENOISE_METHODS:
            _invalid(context, f"method must be one of {sorted(_DENOISE_METHODS)}")
            return analysis_pb2.DenoiseResponse()

        body = {"values": list(request.values), "timestamps": list(request.timestamps), "method": request.method}
        key = cache.make_key(body)
        cached = cache.get(key)
        if cached:
            return _dict_to_denoise_response(cached)

        try:
            result = denoise_service.denoise(list(request.values), list(request.timestamps), request.method)
        except ValueError as exc:
            _invalid(context, str(exc))
            return analysis_pb2.DenoiseResponse()

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return _dict_to_denoise_response(result)

    def Regression(self, request, context):
        if request.model not in _REGRESSION_MODELS:
            _invalid(context, f"model must be one of {sorted(_REGRESSION_MODELS)}")
            return analysis_pb2.RegressionResponse()
        if len(request.values) < 4:
            _invalid(context, "values must have at least 4 elements")
            return analysis_pb2.RegressionResponse()

        degree = request.degree if request.degree > 0 else 3
        body = {"values": list(request.values), "timestamps": list(request.timestamps),
                "model": request.model, "degree": degree}
        key = cache.make_key(body)
        cached = cache.get(key)
        if cached:
            return _dict_to_regression_response(cached)

        try:
            if request.model == "polynomial":
                result = regression_service.polynomial_regression(list(request.values), list(request.timestamps), degree)
            else:
                result = regression_service.bayesian_regression(list(request.values), list(request.timestamps))
        except ValueError as exc:
            _invalid(context, str(exc))
            return analysis_pb2.RegressionResponse()

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return _dict_to_regression_response(result)

    def Predict(self, request, context):
        if request.model not in _PREDICT_MODELS:
            _invalid(context, f"model must be one of {sorted(_PREDICT_MODELS)}")
            return analysis_pb2.PredictResponse()
        if len(request.values) < 4:
            _invalid(context, "values must have at least 4 elements")
            return analysis_pb2.PredictResponse()
        if not (1 <= request.horizon <= 365):
            _invalid(context, "horizon must be between 1 and 365")
            return analysis_pb2.PredictResponse()

        order = tuple(request.arima_order) if request.arima_order else (1, 1, 1)
        body = {"values": list(request.values), "timestamps": list(request.timestamps),
                "model": request.model, "horizon": request.horizon, "arima_order": list(order)}
        key = cache.make_key(body)
        cached = cache.get(key)
        if cached:
            return _dict_to_predict_response(cached)

        try:
            if request.model == "arima":
                result = predict_service.arima_predict(list(request.values), list(request.timestamps), request.horizon, order)
            else:
                result = predict_service.gm11_predict(list(request.values), list(request.timestamps), request.horizon)
        except ValueError as exc:
            _invalid(context, str(exc))
            return analysis_pb2.PredictResponse()

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return _dict_to_predict_response(result)


# ── Proto ↔ dict converters ───────────────────────────────────────────────────

def _dict_to_outliers_response(d: dict) -> analysis_pb2.OutliersResponse:
    stats = d.get("statistics", {})
    return analysis_pb2.OutliersResponse(
        method=d.get("method", ""),
        outliers=[
            analysis_pb2.OutlierEntry(
                index=o.get("index", 0),
                timestamp=o.get("timestamp", ""),
                value=o.get("value", 0.0),
                criterion=o.get("criterion", ""),
                threshold_upper=o.get("threshold_upper", 0.0),
                threshold_lower=o.get("threshold_lower", 0.0),
                z_score=o.get("z_score", 0.0),
                probability=o.get("probability", 0.0),
            )
            for o in d.get("outliers", [])
        ],
        statistics=analysis_pb2.OutliersStatistics(
            mean=stats.get("mean", 0.0),
            std=stats.get("std", 0.0),
            n=stats.get("n", 0),
            outlier_count=stats.get("outlier_count", 0),
        ),
    )


def _dict_to_denoise_response(d: dict) -> analysis_pb2.DenoiseResponse:
    return analysis_pb2.DenoiseResponse(
        denoised_values=d.get("denoised_values", []),
        method=d.get("method", ""),
        params_json=json.dumps(d.get("params", {})),
    )


def _dict_to_regression_response(d: dict) -> analysis_pb2.RegressionResponse:
    return analysis_pb2.RegressionResponse(
        coefficients=d.get("coefficients", []),
        fitted_values=d.get("fitted_values", []),
        r2_score=d.get("r2_score", 0.0),
        model=d.get("model", ""),
        degree=d.get("degree") or 0,
    )


def _dict_to_predict_response(d: dict) -> analysis_pb2.PredictResponse:
    return analysis_pb2.PredictResponse(
        predicted_values=d.get("predicted_values", []),
        predicted_timestamps=d.get("predicted_timestamps", []),
        confidence_lower=d.get("confidence_lower") or [],
        confidence_upper=d.get("confidence_upper") or [],
        model=d.get("model", ""),
        horizon=d.get("horizon", 0),
        order=d.get("order") or [],
    )
