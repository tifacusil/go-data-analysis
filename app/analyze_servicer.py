"""
AnalyzeServicer — implements dataanalysis.v1.AnalysisService.Analyze.

Called by early-warning (circuit-breaker wrapped). Returns trend derived from
the most representative sensor type available for the window. Empty dataset
returns trend="no_data" — never raises an exception that would trip the breaker.
"""
import logging
from datetime import datetime, timezone

import grpc
import pymysql
import pymysql.cursors

from app.config import Config
from app.generated import dataanalysis__v1__pb2, dataanalysis__v1__pb2_grpc
from services import regression_service

logger = logging.getLogger("analyze_servicer")

VERSION = "1.0.0"

# Sensor tables queried in priority order; first non-empty table wins.
_SENSOR_TABLES = [
    ("gnss_readings", "cumulative_displacement_mm"),
    ("deep_displacement_readings", "cumulative_tilt_mm"),
    ("rainfall_readings", "cumulative_rainfall_mm"),
    ("strain_readings", "strain_microstrain"),
    ("soil_pressure_readings", "pressure_kpa"),
]


def _connect() -> pymysql.Connection:
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=3,
        read_timeout=10,
    )


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


class AnalyzeServicer(dataanalysis__v1__pb2_grpc.AnalysisServiceServicer):

    def Analyze(self, request, context):
        project_id = request.project_id
        window_start = request.window_start
        window_end = request.window_end

        if not project_id or not window_start or not window_end:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("project_id, window_start, window_end required")
            return dataanalysis__v1__pb2.AnalyzeResponse()

        try:
            conn = _connect()
        except Exception as exc:
            logger.error("analyze_db_connect_failed project=%s err=%s", project_id, exc)
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("database unavailable")
            return dataanalysis__v1__pb2.AnalyzeResponse()

        try:
            with conn.cursor() as cur:
                for table, value_col in _SENSOR_TABLES:
                    cur.execute(
                        f"SELECT `timestamp`, `{value_col}` AS val "
                        f"FROM `{table}` "
                        f"WHERE project_id = %s AND `timestamp` BETWEEN %s AND %s "
                        f"AND `{value_col}` IS NOT NULL "
                        f"ORDER BY `timestamp` LIMIT 500",
                        (project_id, window_start, window_end),
                    )
                    rows = cur.fetchall()
                    if rows:
                        values = [float(r["val"]) for r in rows]
                        timestamps = [
                            r["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ")
                            if isinstance(r["timestamp"], datetime)
                            else str(r["timestamp"])
                            for r in rows
                        ]
                        trend = _classify_trend(values, timestamps)
                        logger.info(
                            "analyze_ok project=%s table=%s rows=%d trend=%s",
                            project_id, table, len(rows), trend,
                        )
                        return dataanalysis__v1__pb2.AnalyzeResponse(
                            trend=trend,
                            model_version=VERSION,
                            fields={
                                "sensor_table": table,
                                "row_count": str(len(rows)),
                                "window_start": window_start,
                                "window_end": window_end,
                            },
                        )

            # All tables empty for this project/window
            logger.info("analyze_no_data project=%s window=%s/%s", project_id, window_start, window_end)
            return dataanalysis__v1__pb2.AnalyzeResponse(
                trend="no_data",
                model_version=VERSION,
                fields={"reason": "no_readings_in_window"},
            )

        except Exception as exc:
            logger.error("analyze_query_failed project=%s err=%s", project_id, exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"query error: {exc}")
            return dataanalysis__v1__pb2.AnalyzeResponse()
        finally:
            conn.close()
