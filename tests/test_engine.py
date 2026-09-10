"""Smoke test: compute_context arma un subgrafo comprimido sin reventar."""

from leo_code.engine import _get_indexer, compute_context


def test_compute_context_finds_named_function(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python"])

    result = compute_context(str(tmp_path), "say_hello", task_type_in="code_query")

    assert "say_hello" in result["context"]
    assert result["capsules_total"] >= 1
    assert result["tokens"] > 0
    assert result["task_type"] == "code_query"


def test_compute_context_no_code_returns_documents(tmp_path):
    (tmp_path / "notas.md").write_text(
        "# Notas\nEste modulo explica la arquitectura general.\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python", "text"])

    result = compute_context(str(tmp_path), "arquitectura", task_type_in="no_code")

    assert result["task_type"] == "no_code"
    assert isinstance(result["context"], str)
