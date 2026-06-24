"""Tests: CCR — compresión reversible de outputs de tools."""

from leo_code.rag.agent.tools import ToolRegistry


def test_store_and_retrieve_roundtrip():
    reg = ToolRegistry()
    full = "x" * 5000
    ref = reg.store_full(full)
    assert reg.retrieve_full({"ref": ref}) == full


def test_retrieve_unknown_ref():
    reg = ToolRegistry()
    out = reg.retrieve_full({"ref": "nope"})
    assert "no encontrada" in out


def test_refs_are_unique():
    reg = ToolRegistry()
    r1 = reg.store_full("a")
    r2 = reg.store_full("b")
    assert r1 != r2
    assert reg.retrieve_full({"ref": r1}) == "a"
    assert reg.retrieve_full({"ref": r2}) == "b"


def test_retrieve_full_registered_as_tool():
    reg = ToolRegistry()
    names = [d["function"]["name"] for d in reg.get_definitions()]
    assert "retrieve_full" in names
    assert "retrieve_full" in reg._tools
