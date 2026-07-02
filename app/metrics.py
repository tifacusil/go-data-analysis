"""
Prometheus metrics for the HTTP layer.

The default prometheus_client REGISTRY already exports process- and GC-level
metrics (process_resident_memory_bytes, python_gc_*, python_info). Here we add
application-level counters/latency so Prometheus (Sistema B, kubernetes_sd on
pods labelled tier: service) can track throughput and latency per endpoint.
"""
import time

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
