"""
Prometheus metrics for the HTTP and gRPC layers.

The default prometheus_client REGISTRY already exports process- and GC-level
metrics (process_resident_memory_bytes, python_gc_*, python_info). Here we add
application-level counters/latency so Prometheus (Sistema B, kubernetes_sd on
pods labelled tier: service) can track throughput and latency per endpoint and
per gRPC method. Everything lands on the default registry → one /metrics.
"""
import inspect
import time

import grpc
from prometheus_client import Counter, Histogram
from starlette.requests import Request

# Endpoint paths are static (no path params) so label cardinality is bounded.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests processed.",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)

# Path Prometheus scrapes on the pod; excluded from its own metrics.
METRICS_PATH = "/metrics"


async def prometheus_middleware(request: Request, call_next):
    if request.url.path == METRICS_PATH:
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    path = request.url.path
    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
    return response


# ── gRPC ────────────────────────────────────────────────────────────────────
# Method count is small and fixed → label cardinality bounded.
GRPC_REQUEST_COUNT = Counter(
    "grpc_requests_total",
    "Total gRPC requests handled.",
    ["method", "code"],
)
GRPC_REQUEST_LATENCY = Histogram(
    "grpc_request_duration_seconds",
    "gRPC request latency in seconds (whole RPC, DB work included).",
    ["method"],
)


class _CodeCapture:
    """
    Proxy over ServicerContext. Servicers here report failures by calling
    context.set_code(...) and returning normally (no raise), so we record the
    code as it is set. Defaults to OK. All other attribute access delegates to
    the real context.
    """

    def __init__(self, ctx):
        self._ctx = ctx
        self.code = grpc.StatusCode.OK

    def set_code(self, code):
        self.code = code
        return self._ctx.set_code(code)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class GrpcMetricsInterceptor(grpc.aio.ServerInterceptor):
    """Times every unary-unary RPC and counts by method + final status code."""

    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        # Only unary-unary is instrumented; anything else passes through as-is.
        if handler is None or handler.unary_unary is None:
            return handler

        method = handler_call_details.method
        behavior = handler.unary_unary

        async def new_behavior(request, context):
            cap = _CodeCapture(context)
            start = time.perf_counter()
            try:
                result = behavior(request, cap)
                # Servicer methods may be sync or async; normalise.
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception:
                if cap.code is grpc.StatusCode.OK:
                    cap.code = grpc.StatusCode.UNKNOWN
                raise
            finally:
                elapsed = time.perf_counter() - start
                GRPC_REQUEST_LATENCY.labels(method).observe(elapsed)
                GRPC_REQUEST_COUNT.labels(method, cap.code.name).inc()

        return grpc.unary_unary_rpc_method_handler(
            new_behavior,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
