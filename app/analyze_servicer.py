"""
AnalyzeServicer — implements dataanalysis.v1.AnalysisService.Analyze.

Called by early-warning (circuit-breaker wrapped). Returns trend derived from
the most representative sensor type available for the window. Empty dataset
returns trend="no_data" — never raises an exception that would trip the breaker.

Series come from data-management's ReadingService via gRPC (see reading_client);
data-analysis no longer touches the data-management tables directly, so it is no
longer coupled to that service's physical schema (CLAUDE.md §1.2 / §5).
"""
import asyncio
import logging

import grpc

from app import reading_client
from app.generated import dataanalysis_v1_pb2, dataanalysis_v1_pb2_grpc
from services import regression_service

logger = logging.getLogger("analyze_servicer")

VERSION = "1.0.0"

# Sensor types queried in priority order; first non-empty series wins. The value
# is already the canonical column for the type (data-management resolves it), so
# data-analysis knows no table/column names.
_SENSOR_TYPES = [
    "gnss",
    "deep_displacement",
    "rainfall",
    "strain",
    "soil_pressure",
]


def _classify_trend(values: list[float], timestamps: list[str]) -> str:
    """Polynomial regression slope sign → trend label."""
    try:
        result = regression_service.polynomial_regression(values, timestamps, degree=1)
        slope = result["coefficients"][0]
        if abs(slope) < 1e-9:
            return "stable"
        return "accelerating" if slope > 0 else "decelerating"
    except Exception:
        return "stable"


def _analyze_blocking(project_id: str, window_start: str, window_end: str):
    """
    Blocking outbound RPC(s) + regression. Runs in a worker thread (see Analyze)
    so the synchronous gRPC call and its retry backoff never stall the shared
    asyncio event loop.

    Returns (grpc_status_code | None, details | None, AnalyzeResponse). A None
    status code means success; the caller only sets code/details when non-None.
    """
    try:
        for sensor_type in _SENSOR_TYPES:
            points = reading_client.get_series(project_id, sensor_type, window_start, window_end)
            if points:
                values = [float(p.value) for p in points]
                timestamps = [p.timestamp for p in points]
                trend = _classify_trend(values, timestamps)
                logger.info(
                    "analyze_ok project=%s sensor_type=%s points=%d trend=%s",
                    project_id, sensor_type, len(points), trend,
                )
                return (None, None, dataanalysis_v1_pb2.AnalyzeResponse(
                    trend=trend,
                    model_version=VERSION,
                    fields={
                        "sensor_type": sensor_type,
                        "point_count": str(len(points)),
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                ))

        # Every sensor type returned an empty series for this project/window.
        logger.info("analyze_no_data project=%s window=%s/%s", project_id, window_start, window_end)
        return (None, None, dataanalysis_v1_pb2.AnalyzeResponse(
            trend="no_data",
            model_version=VERSION,
            fields={"reason": "no_readings_in_window"},
        ))

    except reading_client.ReadingInvalidArgument as exc:
        logger.error("analyze_invalid_argument project=%s err=%s", project_id, exc)
        return (grpc.StatusCode.INVALID_ARGUMENT, str(exc),
                dataanalysis_v1_pb2.AnalyzeResponse())
    except reading_client.ReadingUnavailable as exc:
        # data-management is down or the breaker is open — degrade by failing
        # fast with UNAVAILABLE (early-warning's own breaker handles it) rather
        # than hammering a service that is not responding.
        logger.error("analyze_upstream_unavailable project=%s err=%s", project_id, exc)
        return (grpc.StatusCode.UNAVAILABLE, f"data-management unavailable: {exc}",
                dataanalysis_v1_pb2.AnalyzeResponse())


class AnalyzeServicer(dataanalysis_v1_pb2_grpc.AnalysisServiceServicer):

    async def Analyze(self, request, context):
        project_id = request.project_id
        window_start = request.window_start
        window_end = request.window_end

        if not project_id or not window_start or not window_end:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("project_id, window_start, window_end required")
            return dataanalysis_v1_pb2.AnalyzeResponse()

        # Offload the blocking outbound RPC + regression to a worker thread; keeps
        # the shared event loop (grpc.aio + uvicorn) free to serve other requests.
        code, details, response = await asyncio.to_thread(
            _analyze_blocking, project_id, window_start, window_end
        )
        if code is not None:
            context.set_code(code)
            context.set_details(details)
        return response
