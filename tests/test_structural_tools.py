"""Tests del retrieval estructural: métodos indexados, tools y verify. Sin LLM, rápidos."""

from pathlib import Path

from leo_code.core.parser import extract_from_file
from leo_code.rag.agent.tools import ToolRegistry, _verify_py

SAMPLE = '''\
class Service:
    """Un servicio."""
    def greet(self, name):
        return helper(name)

def helper(name):
    return f"hi {name}"
'''


def _index(tmp_path) -> dict:
    f = tmp_path / "svc.py"
    f.write_text(SAMPLE, encoding="utf-8")
    caps = extract_from_file(str(f), "python")
    return {c.id: c for c in caps}


def test_parser_emits_methods(tmp_path):
    caps = _index(tmp_path)
    methods = [c for c in caps.values() if c.type == "method"]
    assert any(c.name == "greet" for c in methods), "el método greet debe indexarse como cápsula"


def test_find_and_read_symbol(tmp_path):
    t = ToolRegistry(); t.set_index(_index(tmp_path))
    assert "greet" in t.execute("find_symbol", {"pattern": "greet"}, ".")
    body = t.execute("read_symbol", {"name": "greet"}, ".")
    assert "def" in body and "Service.greet" in body


def test_who_calls_and_callees(tmp_path):
    t = ToolRegistry(); t.set_index(_index(tmp_path))
    # greet llama a helper → helper es callee de greet, greet es caller de helper
    assert "helper" in t.execute("callees", {"name": "greet"}, ".")
    assert "greet" in t.execute("who_calls", {"name": "helper"}, ".")


def test_list_by_kind(tmp_path):
    t = ToolRegistry(); t.set_index(_index(tmp_path))
    out = t.execute("list_by_kind", {"kind": "method"}, ".")
    assert "greet" in out


def test_read_file_caps_large(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(500)), encoding="utf-8")
    t = ToolRegistry()
    out = t.execute("read_file", {"file_path": "big.py"}, str(tmp_path))
    assert "grande" in out.lower() or "read_symbol" in out  # capado, empuja a tool precisa


def test_verify_py_detects_syntax_error(tmp_path):
    good = tmp_path / "g.py"; good.write_text("def f():\n    return 1\n", encoding="utf-8")
    bad = tmp_path / "b.py"; bad.write_text("def f(:\n    pass\n", encoding="utf-8")
    assert "OK" in _verify_py(good)
    assert "SYNTAX ERROR" in _verify_py(bad)
