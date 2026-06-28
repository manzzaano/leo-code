"""Regression: el mensaje assistant que reinyecta tool_calls debe (1) ser UNO solo con
todos los tool_calls, (2) serializar args como JSON (no repr Python), (3) incluir
reasoning_content cuando el modelo de thinking lo exige (DeepSeek V4 → 400 si falta)."""

import json

from leo_code.rag.agent.loop import _assistant_tool_msg


def test_single_message_with_all_tool_calls_json_args():
    tcs = [
        {"name": "list_files", "args": {"path": ".", "depth": 2}, "_id": "c0"},
        {"name": "read_file", "args": {"path": "a.py"}, "_id": "c1"},
    ]
    msg = _assistant_tool_msg("pensando…", tcs)
    assert msg["role"] == "assistant"
    assert len(msg["tool_calls"]) == 2                      # UN mensaje, ambos calls
    args0 = msg["tool_calls"][0]["function"]["arguments"]
    assert json.loads(args0) == {"path": ".", "depth": 2}   # JSON válido, no str(dict)
    assert "reasoning_content" not in msg                   # sin thinking → no se añade


def test_reasoning_content_passed_back_for_thinking_models():
    tcs = [{"name": "x", "args": {}, "_id": "c0"}]
    msg = _assistant_tool_msg("", tcs, reasoning="cadena de pensamiento")
    assert msg["reasoning_content"] == "cadena de pensamiento"
