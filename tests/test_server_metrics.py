"""Tests: GET /metrics/prometheus — formato Prometheus text exposition."""

from fastapi.testclient import TestClient

from leo_code.server.server import app


def test_metrics_prometheus_content_type_and_body():
    with TestClient(app) as client:
        resp = client.get("/metrics/prometheus")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "# TYPE leo_code_queries_total counter" in body
    assert "# TYPE leo_code_avg_latency_ms gauge" in body
    assert "leo_code_uptime_seconds" in body


def test_metrics_tracker_snapshot_reflects_recorded_queries():
    """Llamada directa a MetricsTracker.snapshot() — antes solo se ejercitaba
    indirecto via el endpoint /metrics/prometheus (TestClient -> ASGI -> handler),
    un salto que el guardian estatico de leo no puede trazar (dispatch por ruta,
    no llamada Python directa) — el audit formal lo marcaba falso SIN-test."""
    from leo_code.core.metrics import MetricsTracker

    tracker = MetricsTracker()
    tracker.record_query(tokens=100, latency_ms=50)
    snap = tracker.snapshot()

    assert snap.queries_total == 1
    assert snap.avg_latency_ms == 50


def test_snapshot_to_prometheus_format():
    from leo_code.core.metrics import MetricsSnapshot
    snap = MetricsSnapshot(queries_total=5, avg_latency_ms=12.5)
    out = snap.to_prometheus()
    assert "leo_code_queries_total 5" in out
    assert "leo_code_avg_latency_ms 12.5" in out
    assert out.count("# HELP") == 16
    assert out.count("# TYPE") == 16
