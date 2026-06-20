import requests


def _headers() -> dict:
    from app.config import Config
    return {"X-Consul-Token": Config.CONSUL_TOKEN} if Config.CONSUL_TOKEN else {}


def _base_url() -> str:
    from app.config import Config
    return f"http://{Config.CONSUL_HOST}:{Config.CONSUL_PORT}"


def register() -> None:
    from app.config import Config
    try:
        prefix = (Config.ROUTE_PREFIX or "").strip().rstrip("/")
        health_path = f"{prefix}/health" if prefix else "/health"
        bind = (Config.HTTP_HOST or "").strip()
        check_host = "127.0.0.1" if bind in {"0.0.0.0", "::", ""} else bind

        payload = {
            "ID": Config.INSTANCE_ID,
            "Name": "data-analysis",
            "Port": Config.HTTP_PORT,
            "Tags": [f"version:{Config.VERSION}", "lang-python", f"env:{Config.ENV}"],
            "Check": {
                "HTTP": f"http://{check_host}:{Config.HTTP_PORT}{health_path}",
                "Method": "GET",
                "Interval": "10s",
                "Timeout": "2s",
                "DeregisterCriticalServiceAfter": "1m",
            },
        }
        requests.put(
            f"{_base_url()}/v1/agent/service/register",
            json=payload,
            headers=_headers(),
            timeout=3,
        ).raise_for_status()
    except Exception:
        return


def deregister() -> None:
    from app.config import Config
    try:
        requests.put(
            f"{_base_url()}/v1/agent/service/deregister/{Config.INSTANCE_ID}",
            headers=_headers(),
            timeout=3,
        )
    except Exception:
        return


def is_registered() -> bool:
    from app.config import Config
    try:
        resp = requests.get(
            f"{_base_url()}/v1/agent/service/{Config.INSTANCE_ID}",
            headers=_headers(),
            timeout=2,
        )
        return resp.status_code == 200
    except Exception:
        return False
