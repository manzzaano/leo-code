"""Regression: el grafo de llamadas TS/JS sale del AST (tree-sitter), SOUND+COMPLETE
con la misma regla de callee que el compilador TS. Antes era una regex 74%/60%."""

import pytest

pytest.importorskip("tree_sitter_typescript")

from leo_code.core.parser_ts import extract_from_tree_sitter


def _calls(name, caps):
    return set(next(c for c in caps if c.name == name).calls)


SRC = """\
function top(a, b) {
  helper();
  obj.method(a);
  return qux(a, b);
}

class C {
  m() {
    this.x();
    free();
  }
}
"""


def test_name_and_member_calls():
    caps = extract_from_tree_sitter(SRC, "x.ts", "typescript")
    assert _calls("top", caps) == {"helper", "method", "qux"}   # identifier + member.property
    assert _calls("m", caps) == {"x", "free"}


def test_tagged_template_is_not_a_call():
    # `dedent`...`` es TaggedTemplateExpression para tsc, NO una llamada → no debe aparecer.
    caps = extract_from_tree_sitter("function f(){ dedent`hi ${x}`; real(); }", "x.ts", "typescript")
    assert _calls("f", caps) == {"real"}


def test_call_with_type_arguments_and_unary():
    # `!!forEach<A,B>(x)` — tree-sitter envuelve el callee en unary; debe resolver a forEach.
    src = "function k(els){ return !!forEach<A | B, boolean>(els, x => g(x)); }"
    caps = extract_from_tree_sitter(src, "x.ts", "typescript")
    assert {"forEach", "g"} <= _calls("k", caps)
