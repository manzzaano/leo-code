"""Fix (c) Parte 1: _finalize() nunca debe cerrar con respuesta vacia o cortada
a media frase en silencio — el caso real del benchmark (t7_code_edit) fue una
respuesta que terminaba en "...tener las lineas exactas." sin completar la accion."""

import asyncio

from leo_code.rag.agent.loop import AgentLoop, _looks_truncated, _fallback_summary
from leo_code.rag.llm.provider import Response


def test_looks_truncated_on_length_finish_reason():
    assert _looks_truncated("cualquier texto", finish_reason="length") is True


def test_looks_truncated_on_unclosed_fence():
    assert _looks_truncated("```python\ndef f(): pass") is True


def test_looks_truncated_on_trailing_punctuation_cutoff():
    assert _looks_truncated("Primero, leo la funcion para tener las lineas exactas,") is True


def test_not_truncated_short_fragment_is_ok():
    # el estilo de fragmento corto que _VERBOSITY_BLOCK fomenta NO debe marcarse
    assert _looks_truncated("Linea 42 de utils.py.") is False


def test_empty_text_is_truncated():
    assert _looks_truncated("") is True


def test_fallback_summary_never_empty_and_mentions_query():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c0", "content": "resultado de find_symbol: _plan en goal.py:144"},
    ]
    out = _fallback_summary(messages, "que hace _plan?")
    assert out.strip()
    assert "que hace _plan?" in out
    assert "_plan en goal.py:144" in out


class _OneShotLLM:
    """Primera llamada: texto cortado con finish_reason=length. Segunda: cierra
    limpio. _finalize() debe concatenar ambas y parar (no seguir pidiendo mas)."""

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, tools, temperature=0.3, effort=None):
        self.calls += 1
        if self.calls == 1:
            return Response(text="Primero, leo la funcion para", finish_reason="length")
        return Response(text=" tener las lineas exactas. Listo.", finish_reason="stop")


def test_finalize_continues_truncated_response_once():
    agent = AgentLoop(llm=_OneShotLLM())
    text, tokens = asyncio.run(agent._finalize([{"role": "user", "content": "q"}], "q"))
    assert text == "Primero, leo la funcion para tener las lineas exactas. Listo."
    assert agent.llm.calls == 2


class _AlwaysFailsLLM:
    async def generate(self, messages, tools, temperature=0.3, effort=None):
        raise RuntimeError("boom")


def test_finalize_falls_back_when_llm_always_fails():
    agent = AgentLoop(llm=_AlwaysFailsLLM())
    messages = [{"role": "tool", "tool_call_id": "c0", "content": "algo se investigo"}]
    text, tokens = asyncio.run(agent._finalize(messages, "mi pregunta"))
    assert text.strip()
    assert "mi pregunta" in text
    assert tokens == 0
