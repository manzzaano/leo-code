"""Tests: session manager — SQLite persistence."""

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
