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


def test_awaited_call_with_type_arguments():
    # `await this.get<T>(k)`: tree-sitter envuelve el callee en await_expression.
    caps = extract_from_tree_sitter("async function a(){ await this.get<T>(k); await go<T>(1); }",
                                    "x.ts", "typescript")
    assert _calls("a", caps) == {"get", "go"}


DECORATED = """\
const method3 = "method3";
class C {
    @dec(1) method1() {}
    @dec(2) ["method2"]() {}
    @dec(3) [method3]() {}
    @Get('/x')
    @UseGuards(AuthGuard)
    // comentario entre decorador y método
    findAll() { svc.list(); }
    plain() { other(); }
}
"""


@pytest.mark.parametrize("lang,path", [("typescript", "x.ts"), ("javascript", "x.js")])
def test_member_decorator_calls_belong_to_the_method(lang, path):
    # En tree-sitter TS el decorador de un miembro es HERMANO del method_definition en
    # class_body; tsc (y ast en Python) lo cuelga del método: sus llamadas son del método.
    caps = extract_from_tree_sitter(DECORATED, path, lang)
    assert _calls("method1", caps) == {"dec"}
    assert _calls('["method2"]', caps) == {"dec"}
    assert _calls("[method3]", caps) == {"dec"}
    assert _calls("findAll", caps) == {"Get", "UseGuards", "list"}
    assert _calls("plain", caps) == {"other"}   # el decorador del vecino no se cuela


def test_decorated_method_keeps_its_name_line():
    # file:line del método = línea del nombre (como el `def` en Python), no la del `@`
    caps = extract_from_tree_sitter(DECORATED, "x.ts", "typescript")
    assert next(c for c in caps if c.name == "findAll").start_line == 9


@pytest.mark.parametrize("src,name,expected", [
    # fuera de una función async, `await(x)` es para tsc una llamada al identificador `await`
    ("function f() { const x = await(Promise.resolve(1)); }", "f", {"await", "resolve"}),
    ("class C { m() { await(z()); } }", "m", {"await", "z"}),
    ("async function f() { const g = () => await(y()); }", "f", {"await", "y"}),
    # dentro de una async es un AwaitExpression, sin paréntesis también
    ("async function f() { const x = await(Promise.resolve(1)); }", "f", {"resolve"}),
    ("function f() { const g = async () => await(y()); }", "f", {"y"}),
    ("function f() { await x; }", "f", set()),
])
def test_await_call_outside_async_like_tsc(src, name, expected):
    assert _calls(name, extract_from_tree_sitter(src, "x.ts", "typescript")) == expected


@pytest.mark.parametrize("src,name,expected", [
    # el inicializador de un campo no hereda el async de la función exterior; static {} sí es await
    ("async function f(){ class C { y = await(x()); } }", "f", {"await", "x"}),
    ("function f(){ class C { static { await(x()); } } }", "f", {"x"}),
    # encadenado: `await(a)(b)` y `await(a).foo()` siguen siendo la llamada `await(a)`
    ("function f(){ await(a)(b); }", "f", {"await"}),
    ("function f(){ await(a).foo(); }", "f", {"await", "foo"}),
    ("async function f(){ await(a).foo(); }", "f", {"foo"}),
    # una clave computada se evalúa fuera del método: manda el async exterior
    ("async function f(){ class C { [await(x())]() {} } }", "f", {"x"}),
    ("async function f(){ class C { [await(x())] = 1 } }", "f", {"x"}),
])
def test_await_context_edges_like_tsc(src, name, expected):
    assert _calls(name, extract_from_tree_sitter(src, "x.ts", "typescript")) == expected


def test_same_name_same_line_symbols_keep_distinct_ids():
    # get/set o claves repetidas en una línea: con id archivo:línea:nombre el índice (dict
    # por id) se quedaba con uno y perdía las llamadas del otro
    src = "const o = { get q() { return a(); }, set q(v) { b(); } };\n" \
          "const xs = [{ run: () => c() }, { run: () => d() }];\n"
    caps = extract_from_tree_sitter(src, "x.ts", "typescript")
    assert len({c.id for c in caps}) == len(caps)
    assert sorted(sorted(c.calls) for c in caps if c.name == "q") == [["a"], ["b"]]
    assert sorted(sorted(c.calls) for c in caps if c.name == "run") == [["c"], ["d"]]
    assert "x.ts:1:q" in {c.id for c in caps}   # el primero conserva el id de siempre


def test_quoted_constructor_is_the_constructor_like_tsc():
    # en una clase, `"constructor"() {}` ES el constructor (ES2015); computado u objeto, no
    src = r'''class C { "constructor"() { a(); } }
class D { 'constructor'() { b(); } }
class F { "\x63onstructor"() { c(); } }
class G { "co\nstructor"() { d(); } }
class E { ['constructor']() { e(); } }
var o = { "constructor"() { f(); } };
'''
    names = {c.start_line: c.name for c in extract_from_tree_sitter(src, "x.ts", "typescript")
             if c.type == "method"}
    assert names == {1: "constructor", 2: "constructor", 3: "constructor",
                     4: r'"co\nstructor"', 5: "['constructor']", 6: '"constructor"'}
