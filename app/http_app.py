"""
FastAPI HTTP app — for frontend calls only (proxied through Nginx / Vercel).
Server-to-server consumers (e.g. early-warning-service) must use the gRPC interface.
"""
import logging
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, field_validator

from app import cache, consul
from app.config import Config
from services import outliers_service, denoise_service, regression_service, predict_service

logger = logging.getLogger("http_app")

_ALLOWED_ORIGINS = [
    "https://vite-ews-frontend.vercel.app",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Heartbeat en lugar de register one-shot: si Consul no esta listo al boot,
    # reintenta cada 10s hasta lograrlo (CLAUDE.md 4 — Health checks activos).
    stop = threading.Event()
    consul.start_heartbeat(stop)
    yield
    stop.set()
    consul.deregister()


def create_app() -> FastAPI:
    prefix = (Config.ROUTE_PREFIX or "").strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = f"/{prefix}"

    # docs_url=None desactiva la Swagger UI nativa (que pide /openapi.json con
    # ruta ABSOLUTA y se rompe tras el gateway con prefix /api/v1/analysis/).
    # Más abajo se monta una UI propia que apunta al spec con URL RELATIVA.
    app = FastAPI(title="Data Analysis Service", version=Config.VERSION,
                  lifespan=_lifespan, docs_url=None, redoc_url=None,
                  openapi_url=f"{prefix}/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    # Swagger UI en {prefix}/docs apuntando al spec con URL RELATIVA
    # ("openapi.json"), así resuelve contra la URL pública actual y funciona tras
    # el gateway en /api/v1/analysis/docs sin recompilar. Mismo patrón que el
    # resto del fleet (Go sirve /docs con spec relativo).
    @app.get(f"{prefix}/docs", include_in_schema=False)
    def swagger_ui():
        return get_swagger_ui_html(openapi_url="openapi.json",
                                   title="data-analysis — API docs")

    # ── Schemas ───────────────────────────────────────────────────────────────

    class OutliersRequest(BaseModel):
        values: list[float]
        timestamps: list[str]
        method: Literal["3sigma", "chauvenet", "iqr"]

        @field_validator("values", "timestamps")
        @classmethod
        def not_empty(cls, v):
            if not v:
                raise ValueError("must not be empty")
            return v

    class DenoiseRequest(BaseModel):
        values: list[float]
        timestamps: list[str]
        method: Literal["wavelet", "emd", "svm"]

    class RegressionRequest(BaseModel):
        values: list[float]
        timestamps: list[str]
        model: Literal["polynomial", "bayesian"]
        degree: int = 3

    class PredictRequest(BaseModel):
        values: list[float]
        timestamps: list[str]
        model: Literal["arima", "gm11"]
        horizon: int
        arima_order: list[int] | None = None

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get(f"{prefix}/health")
    def health():
        def _avail(mod: str) -> str:
            try:
                __import__(mod)
                return "available"
            except Exception:
                return "unavailable"

        libs = {m: _avail(m) for m in ("pywt", "PyEMD", "statsmodels")}
        overall = "ok" if all(v == "available" for v in libs.values()) else "degraded"
        return {
            "status": overall,
            "redis": "connected" if cache.ping() else "unavailable",
            "consul": "registered" if consul.is_registered() else "unregistered",
            "version": Config.VERSION,
            "libs": libs,
        }

    @app.post(f"{prefix}/outliers")
    def post_outliers(body: OutliersRequest):
        if len(body.values) != len(body.timestamps):
            return JSONResponse({"error": "validation_error",
                                 "message": "values and timestamps must have the same length"}, 400)
        data = body.model_dump()
        key = cache.make_key(data)
        if hit := cache.get(key):
            return hit

        try:
            result = outliers_service.detect_outliers(body.values, body.timestamps, body.method)
        except ValueError as exc:
            return JSONResponse({"error": "validation_error", "message": str(exc)}, 400)

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return result

    @app.post(f"{prefix}/denoise")
    def post_denoise(body: DenoiseRequest):
        if len(body.values) != len(body.timestamps):
            return JSONResponse({"error": "validation_error",
                                 "message": "values and timestamps must have the same length"}, 400)
        data = body.model_dump()
        key = cache.make_key(data)
        if hit := cache.get(key):
            return hit

        try:
            result = denoise_service.denoise(body.values, body.timestamps, body.method)
        except ValueError as exc:
            return JSONResponse({"error": "validation_error", "message": str(exc)}, 400)

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return result

    @app.post(f"{prefix}/regression")
    def post_regression(body: RegressionRequest, request: Request):
        if len(body.values) < 4:
            return JSONResponse({"error": "validation_error", "message": "values must have at least 4 elements"}, 400)
        if len(body.values) != len(body.timestamps):
            return JSONResponse({"error": "validation_error",
                                 "message": "values and timestamps must have the same length"}, 400)
        if body.model == "polynomial" and not (1 <= body.degree < len(body.values)):
            return JSONResponse({"error": "validation_error",
                                 "message": f"degree must be >= 1 and < {len(body.values)}"}, 400)

        data = body.model_dump()
        key = cache.make_key(data)
        if hit := cache.get(key):
            return JSONResponse(hit, headers={"X-Cache": "HIT"})

        try:
            if body.model == "polynomial":
                result = regression_service.polynomial_regression(body.values, body.timestamps, body.degree)
            else:
                result = regression_service.bayesian_regression(body.values, body.timestamps)
        except ValueError as exc:
            return JSONResponse({"error": "validation_error", "message": str(exc)}, 400)
        except Exception:
            logger.exception("Unexpected error in regression")
            return JSONResponse({"error": "internal_error", "message": "An unexpected error occurred"}, 500)

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return JSONResponse(result, headers={"X-Cache": "MISS"})

    @app.post(f"{prefix}/predict")
    def post_predict(body: PredictRequest):
        if len(body.values) < 4:
            return JSONResponse({"error": "validation_error", "message": "values must have at least 4 elements"}, 400)
        if len(body.values) != len(body.timestamps):
            return JSONResponse({"error": "validation_error",
                                 "message": "values and timestamps must have the same length"}, 400)
        if not (1 <= body.horizon <= 365):
            return JSONResponse({"error": "validation_error", "message": "horizon must be between 1 and 365"}, 400)
        if body.arima_order is not None and (len(body.arima_order) != 3 or any(v < 0 for v in body.arima_order)):
            return JSONResponse({"error": "validation_error",
                                 "message": "arima_order must be a list of 3 non-negative integers"}, 400)

        order = tuple(body.arima_order) if body.arima_order else (1, 1, 1)
        data = body.model_dump()
        key = cache.make_key(data)
        if hit := cache.get(key):
            return JSONResponse(hit, headers={"X-Cache": "HIT"})

        try:
            if body.model == "arima":
                result = predict_service.arima_predict(body.values, body.timestamps, body.horizon, order)
            else:
                result = predict_service.gm11_predict(body.values, body.timestamps, body.horizon)
        except ValueError as exc:
            return JSONResponse({"error": "validation_error", "message": str(exc)}, 400)
        except Exception:
            logger.exception("Unexpected error in predict")
            return JSONResponse({"error": "internal_error", "message": "An unexpected error occurred"}, 500)

        cache.set(key, result, Config.REDIS_CACHE_TTL_SECONDS)
        return JSONResponse(result, headers={"X-Cache": "MISS"})

    return app
