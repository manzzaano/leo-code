"""Smoke test: sin Redis disponible (_client=None, estado por defecto del módulo),
las operaciones de cache deben degradar a no-op en vez de reventar; el circuit
breaker abre tras N fallos consecutivos."""

from leo_code.core import cache


def test_writers_are_safe_noop_without_client():
    cache._client = None
    cache._failures = 0
    cache._last_failure = 0.0

    assert cache.is_available() is False
    cache.cache_result("una query", {"a": 1})       # no debe reventar
    cache.cache_subgraph("entidad-1", {"n": 1})      # no debe reventar
    cache.cache_ontology("dominio-x", {"o": 1})      # no debe reventar
    assert cache.get_cached_result("una query") is None


def test_circuit_breaker_opens_after_threshold_and_recovers():
    cache._client = object()  # simula cliente presente, sin conexion real
    cache._failures = 0
    cache._last_failure = 0.0

    for _ in range(cache.CB_THRESHOLD):
        cache._record_failure()
    assert cache._is_circuit_open() is True

    cache._record_success()
    assert cache._is_circuit_open() is False

    cache._client = None  # deja el modulo limpio para otros tests
