import hashlib
import json
from typing import Any, Mapping

import redis

_CACHE_PREFIX = "analysis_cache:"
_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        from app.config import Config
        _client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD,
            decode_responses=True,
        )
    return _client


def make_key(body: Mapping[str, Any]) -> str:
    normalized = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


def get(key: str) -> dict | None:
    try:
        raw = _get_client().get(key)
    except Exception:
        return None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def set(key: str, value: dict, ttl: int) -> None:
    try:
        _get_client().setex(key, ttl, json.dumps(value))
    except Exception:
        return


def ping() -> bool:
    try:
        return bool(_get_client().ping())
    except Exception:
        return False
