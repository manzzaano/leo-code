"""Las instructions del servidor son lo que el agente lee para decidir cómo usar leo-mcp
(Claude Code las muestra aunque difiera las tools). Lo que prometen debe ser cierto:
estos tests fijan cada promesa contra el comportamiento real."""

from leo_code.server import mcp_server
from leo_code.server.mcp_server import INSTRUCTIONS, _GRAPH_OPS

from test_mcp_product import _write, fresh_engine  # noqa: F401 (fixture)


def test_instructions_name_every_graph_op_and_get_context():
    for op in _GRAPH_OPS:
        assert op in INSTRUCTIONS, op
    assert "get_context" in INSTRUCTIONS


def test_instructions_warn_that_values_and_decorators_are_not_calls():
    # who_calls/impact cuentan llamadas; una función usada como valor o decorador
    # no aparece: sin el aviso, «no results» se lee como «nadie la usa».
    low = INSTRUCTIONS.lower()
    assert "decorator" in low and "callback" in low
    assert "who_calls and impact count calls only" in low


def test_values_are_missing_from_who_calls_but_python_guard_sees_them(fresh_engine):
    repo = fresh_engine / "r"
    _write(repo / "a.py",
           "def deco(f):\n    return f\n\n@deco\ndef g():\n    return 1\n\n"
           "def cb(x):\n    return x\n\ndef use():\n    return list(map(cb, [1]))\n")
    _write(repo / "web.ts",
           "export function helper() { return 1 }\n"
           "export function run() { return [1].map(helper) }\n")
    q = lambda op, s: mcp_server._graph({"op": op, "symbol": s, "repo_path": str(repo)})
    # lo que dicen las instructions, en el mismo orden
    assert "no results" in q("who_calls", "cb")
    assert "no results" in q("impact", "cb")
    assert "use (function)" in q("guard", "cb")           # guard: referencias en Python
    assert "breaks nothing" in q("guard", "helper")       # TS: el valor no cuenta
    assert "breaks nothing" in q("guard", "deco")         # decorador: no cuenta
    assert "python" in INSTRUCTIONS.lower().split("guard also counts")[1][:80]
