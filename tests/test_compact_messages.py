"""Fix (b): _compact_messages respeta keep_last, no separa pares
assistant(tool_calls)/tool, y run()/stream_run() eligen keep_last segun breadth
(evita reenviar el historial completo en cada iteracion del loop de tools)."""

import asyncio

from leo_code.rag.agent.loop import (
    AgentLoop, _compact_messages, _assistant_tool_msg,
)
from leo_code.rag.llm.provider import Response


def _history(n_pairs: int) -> list[dict]:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "query original"},
    ]
    for i in range(n_pairs):
        messages.append(_assistant_tool_msg(f"pensando {i}", [
            {"name": f"tool_{i}", "args": {"n": i}, "_id": f"c{i}"},
        ]))
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"resultado {i}"})
    return messages


def test_respects_keep_last():
    messages = _history(20)
    out = _compact_messages(messages, keep_last=6)
    assert len(out) < len(messages)
    assert out[0]["role"] == "system" and out[1]["role"] == "user"


def test_below_threshold_returns_unchanged():
    messages = _history(2)
    out = _compact_messages(messages, keep_last=16)
    assert out == messages


def test_never_separates_tool_call_pair():
    messages = _history(20)
    out = _compact_messages(messages, keep_last=6)
    for i, m in enumerate(out):
        if m.get("role") == "tool":
            prev = out[i - 1]
            assert prev.get("role") == "assistant" and prev.get("tool_calls"), (
                "un mensaje 'tool' quedo sin su 'assistant' con tool_calls precedente")


def test_summary_notes_dropped_tool_names():
    messages = _history(20)
    out = _compact_messages(messages, keep_last=6)
    summary = next(m for m in out if m.get("role") == "system" and "compactado" in m.get("content", ""))
    assert "Ya se llamo" in summary["content"]
    assert "tool_0" in summary["content"]  # la primera tool-call colapsada aparece
    assert len(summary["content"]) < 400   # barato, no un resumen largo


def test_summary_short_when_no_dropped_calls():
    # Todo el historial cabe en 'recent': no hay nada que colapsar -> se devuelve igual.
    messages = _history(1)
    out = _compact_messages(messages, keep_last=16)
    assert out == messages


class _FakeLLM:
    """Devuelve una respuesta final (sin tool_calls) en la primera llamada — basta
    UNA iteracion del loop para observar el keep_last que run()/stream_run() eligen,
    _compact_messages se llama en cada iteracion sin importar si compacta algo."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, tools, temperature=0.2, effort=None):
        self.calls += 1
        return Response(text="respuesta final", tool_calls=[])


def _spy_compact(monkeypatch):
    seen: list[int] = []
    original = _compact_messages

    def spy(messages, keep_last=6):
        seen.append(keep_last)
        return original(messages, keep_last=keep_last)

    monkeypatch.setattr("leo_code.rag.agent.loop._compact_messages", spy)
    return seen


def _run_agent(tmp_path, query: str, monkeypatch):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    seen = _spy_compact(monkeypatch)
    agent = AgentLoop(llm=_FakeLLM(), max_iterations=3)
    asyncio.run(agent.run(query, repo_path=str(tmp_path), use_kc_rag=True))
    return seen


def test_run_uses_wide_keep_last_for_breadth_task(tmp_path, monkeypatch):
    seen = _run_agent(tmp_path, "haz code review de este repo", monkeypatch)
    assert seen and seen[0] == 16


def test_run_uses_narrow_keep_last_for_normal_task(tmp_path, monkeypatch):
    seen = _run_agent(tmp_path, "que hace la funcion foo", monkeypatch)
    assert seen and seen[0] == 12
