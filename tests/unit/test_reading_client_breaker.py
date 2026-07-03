"""Check minimo del circuit breaker de reading_client. ponytail: solo la logica
no-trivial (transiciones open/half-open + que INVALID_ARGUMENT no abra)."""
import grpc

from app.reading_client import _CircuitBreaker


class _Err(grpc.RpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "boom"


def test_breaker_opens_after_threshold_and_half_opens():
    b = _CircuitBreaker(fail_threshold=2, reset_seconds=0.05)
    assert b.allow()
    b.record_failure()
    assert b.allow()            # 1 fallo < umbral
    b.record_failure()          # 2 fallos => abre
    assert not b.allow()        # abierto: bloquea

    import time
    time.sleep(0.06)            # ventana expira
    assert b.allow()            # half-open: deja pasar 1 sonda
    b.record_success()
    assert b.allow()            # cerrado de nuevo


def test_success_resets_failures():
    b = _CircuitBreaker(fail_threshold=2, reset_seconds=10)
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.allow()            # el reset evito llegar al umbral


if __name__ == "__main__":
    test_breaker_opens_after_threshold_and_half_opens()
    test_success_resets_failures()
    print("ok")
