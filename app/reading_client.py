"""
Client for data-management's datamanagement.v1.ReadingService.GetReadingSeries.

Replaces the direct pymysql access data-analysis used to have against the
data-management tables (that broke database-per-service, CLAUDE.md §1.2). The
call is a synchronous outbound RPC, so it is wrapped in the resilience triad
required by CLAUDE.md §5:

  * explicit per-call timeout   (stub.GetReadingSeries(req, timeout=...))
  * retry with exponential backoff  (max 3: 1s / 5s / 30s)
  * circuit breaker             — once open the call fails fast (degrade), it is
                                  not retried hard against a service that is down

An empty series (points=[]) is NOT an error: it is returned as an empty list and
the caller maps it to trend="no_data". Only real failures (DB down → INTERNAL,
transport → UNAVAILABLE) are retried / counted against the breaker.
"""
import logging
import threading
import time

import grpc

from app.config import Config
from app.generated import readings_pb2, readings_pb2_grpc

logger = logging.getLogger("reading_client")

# gRPC codes worth retrying: transient server / transport failures.
_RETRYABLE = frozenset({
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
})


class ReadingUnavailable(Exception):
    """data-management is unreachable/erroring (retries exhausted or breaker open)."""


class ReadingInvalidArgument(Exception):
    """data-management rejected the request as malformed (not retryable)."""


class _CircuitBreaker:
    """
    Minimal thread-safe breaker. Opens after `fail_threshold` consecutive
    failures and stays open for `reset_seconds`; the first call after that runs
    as a half-open trial (success closes it, failure re-opens it).
    """

    def __init__(self, fail_threshold: int, reset_seconds: float):
        self._fail_threshold = max(1, fail_threshold)
        self._reset_seconds = reset_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._open = False

    def allow(self) -> bool:
        with self._lock:
            if not self._open:
                return True
            if (time.monotonic() - self._opened_at) >= self._reset_seconds:
                # half-open trial: let one call through
                self._open = False
                self._failures = self._fail_threshold - 1
                logger.info("reading_breaker_half_open")
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._fail_threshold and not self._open:
                self._open = True
                self._opened_at = time.monotonic()
                logger.warning("reading_breaker_open failures=%d", self._failures)


_breaker = _CircuitBreaker(Config.DM_BREAKER_FAIL_THRESHOLD, Config.DM_BREAKER_RESET_SECONDS)

_channel_lock = threading.Lock()
_channel: grpc.Channel | None = None
_stub: readings_pb2_grpc.ReadingServiceStub | None = None


def _get_stub() -> readings_pb2_grpc.ReadingServiceStub:
    """Lazily build a reusable insecure channel/stub (server-to-server, in-cluster)."""
    global _channel, _stub
    if _stub is not None:
        return _stub
    with _channel_lock:
        if _stub is None:
            _channel = grpc.insecure_channel(Config.DATA_MANAGEMENT_GRPC_ADDR)
            _stub = readings_pb2_grpc.ReadingServiceStub(_channel)
            logger.info("reading_client_connected addr=%s", Config.DATA_MANAGEMENT_GRPC_ADDR)
    return _stub


def get_series(project_id: str, sensor_type: str, window_start: str, window_end: str):
    """
    Fetch the canonical series for one sensor_type. Returns a list of
    readings_pb2.SeriesPoint (possibly empty). Raises ReadingInvalidArgument on
    a malformed request or ReadingUnavailable when data-management is down /
    the breaker is open.
    """
    if not _breaker.allow():
        logger.warning("reading_call_skipped_breaker_open sensor_type=%s", sensor_type)
        raise ReadingUnavailable("data-management circuit open")

    stub = _get_stub()
    req = readings_pb2.GetReadingSeriesRequest(
        project_id=project_id,
        sensor_type=sensor_type,
        window_start=window_start,
        window_end=window_end,
        limit=0,  # 0 => server default (500)
    )

    backoffs = Config.DM_RETRY_BACKOFF_SECONDS
    last_exc: grpc.RpcError | None = None
    for attempt in range(len(backoffs) + 1):
        try:
            resp = stub.GetReadingSeries(req, timeout=Config.DM_CALL_TIMEOUT_SECONDS)
            _breaker.record_success()
            return list(resp.points)
        except grpc.RpcError as exc:
            code = exc.code()
            if code == grpc.StatusCode.INVALID_ARGUMENT:
                # our contract error — retrying won't help, don't trip the breaker
                logger.error("reading_invalid_argument sensor_type=%s detail=%s",
                             sensor_type, exc.details())
                raise ReadingInvalidArgument(exc.details() or "invalid argument") from exc
            if code not in _RETRYABLE:
                _breaker.record_failure()
                raise ReadingUnavailable(f"{code}: {exc.details()}") from exc

            _breaker.record_failure()
            last_exc = exc
            if attempt < len(backoffs):
                delay = backoffs[attempt]
                logger.warning("reading_call_retry sensor_type=%s attempt=%d code=%s backoff=%ss",
                               sensor_type, attempt + 1, code, delay)
                time.sleep(delay)

    detail = last_exc.details() if last_exc else "unknown"
    logger.error("reading_call_exhausted sensor_type=%s detail=%s", sensor_type, detail)
    raise ReadingUnavailable(f"retries exhausted: {detail}")
