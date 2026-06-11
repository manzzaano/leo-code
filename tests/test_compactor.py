"""Tests: compactor — compactación de historial de sesión."""

from leo_code.session.compactor import compact_history


def _message(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_compact_empty_history():
    result = compact_history([])
    assert result == []


def test_compact_under_threshold():
    messages = [_message("user", f"mensaje {i}") for i in range(10)]
    result = compact_history(messages)
    assert result == messages


def test_compact_above_threshold():
    messages = [_message("user", f"mensaje {i}") for i in range(50)]
    result = compact_history(messages)
    assert len(result) < 50
    assert result[0]["role"] == "system"
    assert "Resumen" in result[0]["content"]
    assert result[-1] == messages[-1]
