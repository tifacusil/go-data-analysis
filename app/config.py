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
