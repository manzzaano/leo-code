"""Tests: memoria persistente cross-sesión (Mem0 pattern) + compactor token-trigger."""

import pytest

from leo_code.session import SessionManager
from leo_code.session.compactor import compact_history


@pytest.fixture
def sm():
    return SessionManager(db_path=":memory:")


def test_remember_and_recall(sm):
    sm.remember("/repo", "El parser usa tree-sitter para multi-lenguaje")
    sm.remember("/repo", "Los tests corren con pytest -q")
    hits = sm.recall("/repo", "como funciona el parser multi-lenguaje")
    assert any("tree-sitter" in h for h in hits)


def test_recall_scoped_by_repo(sm):
    sm.remember("/repoA", "secreto del repo A")
    sm.remember("/repoB", "secreto del repo B")
    hits = sm.recall("/repoA", "secreto")
    assert hits == ["secreto del repo A"]


def test_remember_dedup(sm):
    assert sm.remember("/repo", "fact unico") is True
    assert sm.remember("/repo", "fact unico") is False  # duplicado


def test_recall_no_match(sm):
    sm.remember("/repo", "algo sobre el indexer")
    assert sm.recall("/repo", "xyzzy plugh quux") == []


def test_recall_empty_query(sm):
    sm.remember("/repo", "fact")
    assert sm.recall("/repo", "") == []


# ── compactor token-trigger ──────────────────────────────────────────────────


def test_compact_token_trigger_under_budget():
    msgs = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "qué tal"}]
    # budget enorme → no compacta, mismo objeto
    assert compact_history(msgs, max_tokens=100000) is msgs


def test_compact_token_trigger_over_budget():
    # muchos mensajes grandes con budget pequeño → compacta
    msgs = [{"role": "user", "content": "palabra " * 200} for _ in range(20)]
    result = compact_history(msgs, max_tokens=2000, trigger_ratio=0.7, reserve_ratio=0.4)
    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith("[Resumen de conversacion anterior]")
    assert len(result) < len(msgs)


def test_compact_custom_summarizer():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    out = compact_history(msgs, max_messages=30, summarizer=lambda old: "RESUMEN-LLM")
    assert "RESUMEN-LLM" in out[0]["content"]
