import os


class Config:
    # HTTP
    HTTP_HOST = os.environ.get("ANALYSIS__HOST", "0.0.0.0")
    HTTP_PORT = int(os.environ.get("ANALYSIS__HTTP_PORT", 8080))
    ROUTE_PREFIX = (os.environ.get("ANALYSIS__ROUTE_PREFIX", "") or "").strip()

    # gRPC (server-to-server only; never exposed through Nginx)
    GRPC_PORT = int(os.environ.get("ANALYSIS__GRPC_PORT", 50051))
    GRPC_MAX_WORKERS = int(os.environ.get("ANALYSIS__GRPC_MAX_WORKERS", 10))

    ENV = os.environ.get("ANALYSIS__ENV", "dev")
    VERSION = os.environ.get("ANALYSIS__VERSION", "1.0.0")

    # Redis
    REDIS_HOST = os.environ.get("ANALYSIS__REDIS__HOST", "localhost")
    REDIS_PORT = int(os.environ.get("ANALYSIS__REDIS__PORT", 6379))
    REDIS_PASSWORD = os.environ.get("ANALYSIS__REDIS__PASSWORD") or None
    REDIS_CACHE_TTL_SECONDS = int(os.environ.get("ANALYSIS__REDIS__CACHE_TTL_SECONDS", 3600))

    # data-management ReadingService (gRPC). Reemplaza el acceso directo pymysql
    # a las tablas de data-management (viola database-per-service). Se resuelve
    # por DNS de k8s (data-management:9090); sin Consul.
    DATA_MANAGEMENT_GRPC_ADDR = os.environ.get("DATA_MANAGEMENT_GRPC_ADDR", "data-management:9090")
    # Resiliencia de la llamada saliente sincrona (CLAUDE.md §5).
    DM_CALL_TIMEOUT_SECONDS = float(os.environ.get("DATA_MANAGEMENT_CALL_TIMEOUT_SECONDS", 5.0))
    DM_RETRY_BACKOFF_SECONDS = [
        float(s) for s in os.environ.get("DATA_MANAGEMENT_RETRY_BACKOFF_SECONDS", "1,5,30").split(",") if s
    ]
    DM_BREAKER_FAIL_THRESHOLD = int(os.environ.get("DATA_MANAGEMENT_BREAKER_FAIL_THRESHOLD", 3))
    DM_BREAKER_RESET_SECONDS = float(os.environ.get("DATA_MANAGEMENT_BREAKER_RESET_SECONDS", 30.0))
