import logging
import threading

import requests

logger = logging.getLogger("consul")


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
            # Address = la direccion por la que el resto del sistema alcanza esta
            # instancia (mismo host que el check). Sin esto Consul devuelve
            # ServiceAddress vacio y consul-template no puede armar el upstream de
            # nginx -> 502. Es el hostname del contenedor (via ANALYSIS__HOST).
            "Address": check_host,
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
        logger.info("consul register ok id=%s", Config.INSTANCE_ID)
    except Exception as exc:
        # No swallow silencioso: el registro fallaba sin dejar rastro (CLAUDE.md 1.8, 5).
        logger.warning("consul register fallo: %s", exc)
        raise


_HEARTBEAT_INTERVAL = 10.0  # s; re-registra periodicamente como el Registrar de Go (CLAUDE.md 4)


def start_heartbeat(stop: threading.Event) -> threading.Thread:
    """Re-registra en loop hasta que stop se active. Garantiza recuperacion si
    Consul no estaba listo al boot (race de arranque) — mismo patron que el
    Registrar.Run de los servicios Go. Bloquea: corre en thread daemon."""
    def _loop() -> None:
        while not stop.is_set():
            try:
                register()
            except Exception:
                pass  # ya logueado en register()
            stop.wait(_HEARTBEAT_INTERVAL)

    t = threading.Thread(target=_loop, name="consul-heartbeat", daemon=True)
    t.start()
    return t


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
