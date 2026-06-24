"""Tests: effort routing — detección de error + capping de tokens por esfuerzo."""

from leo_code.rag.agent.loop import _looks_like_error
from leo_code.rag.llm.provider import LLMProvider


def test_looks_like_error_detects_markers():
    assert _looks_like_error("Traceback (most recent call last):")
    assert _looks_like_error("[Bloqueado: sin permiso]")
    assert _looks_like_error("Error: file not found")
    assert _looks_like_error("la operación falló")


def test_looks_like_error_clean_output():
    assert not _looks_like_error("def foo(): return 1")
    assert not _looks_like_error("3 archivos encontrados, 12 símbolos")
    assert not _looks_like_error("")


def test_effort_max_tokens_caps_on_low():
    # low capa al mínimo; high/None pasan el default
    assert LLMProvider._effort_max_tokens(16384, "low") == 2048
    assert LLMProvider._effort_max_tokens(4096, "low") == 2048
    assert LLMProvider._effort_max_tokens(1024, "low") == 1024   # ya menor que el cap
    assert LLMProvider._effort_max_tokens(8192, "high") == 8192
    assert LLMProvider._effort_max_tokens(8192, None) == 8192
