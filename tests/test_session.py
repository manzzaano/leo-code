"""Tests: session manager — SQLite persistence + compactor."""

import pytest
from leo_code.session import SessionManager


@pytest.fixture
def sm():
    m = SessionManager(db_path=":memory:")
    return m


def test_create_session(sm):
    s = sm.create_session("/repo", "anthropic/claude-sonnet-4")
    assert s.id
    assert s.repo_path == "/repo"
    assert s.model == "anthropic/claude-sonnet-4"
    assert s.message_count == 0


def test_add_message(sm):
    s = sm.create_session("/repo")
    msg = sm.add_message(s.id, "user", "hola", tokens=10)
    assert msg.role == "user"
    assert msg.content == "hola"
    assert msg.tokens == 10
    assert msg.id > 0


def test_get_history(sm):
    s = sm.create_session("/repo")
    sm.add_message(s.id, "user", "pregunta")
    sm.add_message(s.id, "assistant", "respuesta", tokens=50)
    history = sm.get_history(s.id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_get_history_empty(sm):
    s = sm.create_session("/repo")
    history = sm.get_history(s.id)
    assert history == []


def test_list_sessions(sm):
    sm.create_session("/repo1")
    sm.create_session("/repo2")
    sessions = sm.list_sessions()
    assert len(sessions) == 2


def test_delete_session(sm):
    s = sm.create_session("/repo")
    sm.delete_session(s.id)
    assert sm.get_session(s.id) is None


def test_get_session_not_found(sm):
    assert sm.get_session("nonexistent") is None


def test_session_messages_deleted_cascade(sm):
    s = sm.create_session("/repo")
    sm.add_message(s.id, "user", "test")
    sm.delete_session(s.id)
    assert sm.get_session(s.id) is None


# ── compactor ──────────────────────────────────────────────────────────────────


def _make_messages(n: int) -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"mensaje {i}"}
            for i in range(n)]


def test_compact_empty():
    from leo_code.session.compactor import compact_history
    assert compact_history([], max_messages=30) == []


def test_compact_under_threshold():
    from leo_code.session.compactor import compact_history
    msgs = _make_messages(10)
    result = compact_history(msgs, max_messages=30)
    assert result is msgs
    assert len(result) == 10


def test_compact_over_threshold():
    from leo_code.session.compactor import compact_history
    msgs = _make_messages(50)
    result = compact_history(msgs, max_messages=30)
    assert len(result) <= 30
    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith("[Resumen de conversacion anterior]")
    assert result[-1] == msgs[-1]
