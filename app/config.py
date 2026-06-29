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

    # MySQL data-management (read-only access for Analyze RPC).
    # Accepts both ANALYSIS__MYSQL__* (new) and MYSQL_* (legacy configmap) keys.
    MYSQL_HOST = os.environ.get("ANALYSIS__MYSQL__HOST") or os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("ANALYSIS__MYSQL__PORT") or os.environ.get("MYSQL_PORT", 3306))
    MYSQL_USER = os.environ.get("ANALYSIS__MYSQL__USER") or os.environ.get("MYSQL_USER", "svc_data_analysis_ro")
    MYSQL_PASSWORD = os.environ.get("ANALYSIS__MYSQL__PASSWORD") or os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DB = os.environ.get("ANALYSIS__MYSQL__DB") or os.environ.get("MYSQL_DATABASE", "data_management")
