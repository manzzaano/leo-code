"""record_query() escribe una línea a usage.jsonl (global, alimenta leo_code/meter/)
además de llevar el tracking en memoria existente. Un fallo de disco no debe
propagar y romper la query real (es telemetría, no critical path)."""
import json

import leo_code.core.metrics as metrics


def test_record_query_escribe_una_linea_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "usage.jsonl"
    monkeypatch.setattr(metrics, "USAGE_LOG_PATH", log_path)

    metrics.get_metrics().record_query(
        123, 45, repo_path="C:\\fake\\repo", model="deepseek/deepseek-chat")

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tokens"] == 123
    assert entry["latency_ms"] == 45
    assert entry["repo_path"] == "C:\\fake\\repo"
    assert entry["model"] == "deepseek/deepseek-chat"
    assert "ts" in entry


def test_record_query_acumula_lineas(tmp_path, monkeypatch):
    log_path = tmp_path / "usage.jsonl"
    monkeypatch.setattr(metrics, "USAGE_LOG_PATH", log_path)

    metrics.get_metrics().record_query(10, 1)
    metrics.get_metrics().record_query(20, 2)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_record_query_defaults_repo_path_model_vacios(tmp_path, monkeypatch):
    log_path = tmp_path / "usage.jsonl"
    monkeypatch.setattr(metrics, "USAGE_LOG_PATH", log_path)

    metrics.get_metrics().record_query(5, 1)

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["repo_path"] == ""
    assert entry["model"] == ""


def test_record_query_fallo_de_escritura_no_propaga(tmp_path, monkeypatch):
    # Directorio inexistente Y no creable (apunta el path DENTRO de un archivo,
    # no un directorio -> mkdir falla) fuerza el except silencioso.
    blocker = tmp_path / "blocker_is_a_file"
    blocker.write_text("x")
    bad_path = blocker / "usage.jsonl"
    monkeypatch.setattr(metrics, "USAGE_LOG_PATH", bad_path)

    # No debe lanzar excepcion.
    metrics.get_metrics().record_query(1, 1)
