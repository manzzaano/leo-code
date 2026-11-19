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


def test_exported_decorated_class_like_non_exported():
    # `@Dec() export class A`: el decorador cuelga del export_statement en tree-sitter; para tsc
    # (y para leo sin export) es de la clase: su llamada y la línea del `@`
    src = "@Injectable()\nexport class A { m() { x(); } }\n@Dec()\nclass B {}\n" \
          "@Dec() export default class D {}\n"
    caps = {c.name: c for c in extract_from_tree_sitter(src, "x.ts", "typescript")}
    assert (caps["A"].start_line, set(caps["A"].calls)) == (1, {"Injectable", "x"})
    assert (caps["B"].start_line, set(caps["B"].calls)) == (3, {"Dec"})
    assert (caps["D"].start_line, set(caps["D"].calls)) == (5, {"Dec"})
    assert caps["m"].start_line == 2


def test_abstract_then_newline_class_starts_at_class_like_tsc():
    # `abstract⏎class B {}`: por ASI `abstract` es otra sentencia y B empieza en `class`.
    src = "abstract\nclass B {}\nabstract class A {}\n@d() export abstract class Z {}\n"
    lines = {c.name: c.start_line for c in extract_from_tree_sitter(src, "x.ts", "typescript")}
    assert lines == {"B": 2, "A": 3, "Z": 4}


def test_export_newline_decorated_class_starts_at_export_like_tsc():
    # `export⏎@D()⏎class C`: tree-sitter lo lee como `export` suelto + clase (sin error);
    # para tsc es una clase exportada que empieza en `export`
    src = "export\n@D()\nclass C { m() { a(); } }\nexport\n  @E class F {}\n"
    caps = {c.name: c for c in extract_from_tree_sitter(src, "x.ts", "typescript")}
    assert (caps["C"].start_line, set(caps["C"].calls)) == (1, {"D", "a"})
    assert (caps["F"].start_line, caps["m"].start_line) == (4, 3)


def test_interface_then_newline_is_not_an_interface_like_tsc():
    # `interface⏎I⏎{}`: por ASI son dos identificadores y un bloque, no una interfaz
    src = "function f() {\n  interface\n  I\n  {}\n}\ninterface J {}\n"
    names = {c.name for c in extract_from_tree_sitter(src, "x.ts", "typescript")}
    assert names == {"f", "J"}


@pytest.mark.parametrize("path,lang", [("x.ts", "typescript"), ("x.js", "javascript")])
def test_accessor_keyword_on_its_own_line_like_tsc(path, lang):
    # `get⏎x() {}` es un accessor para tsc (empieza en `get`); tree-sitter da campo + método
    src = "class C {\n  get\n  x() { return 1 }\n  set\n  x(v) { }\n  y() {}\n}\n"
    lines = sorted((c.name, c.start_line) for c in extract_from_tree_sitter(src, path, lang)
                   if c.type == "method")
    assert lines == [("x", 2), ("x", 4), ("y", 6)]


@pytest.mark.parametrize("src,name,expected", [
    # nivel superior de un módulo (import/export) es contexto await; el de un script no
    ("export {};\nclass K { [await(1)]() {} }", "K", set()),
    ("class K { [await(1)]() {} }", "K", {"await"}),
    # el decorador de un campo o de un parámetro se evalúa fuera de su dueño
    ("async function g(){ class D { @dec(await(3)) x = 1; } }", "g", {"dec"}),
    ("async function g(){ class D { m(@dec(await(4)) p) {} } }", "g", {"dec"}),
    ("class A { async m(@dec(await(1)) p) {} }", "A", {"await", "dec"}),
    # el decorador de un método no salta la función exterior
    ("async function g(){ class D { @dec(await(5)) m() {} } }", "g", {"dec"}),
    # comentario entre `await` y `(`, y `await<T>(x)`
    ("function e(){ await /* c */ (1); }", "e", {"await"}),
    ("function e(){ await<number>(5); }", "e", {"await"}),
])
def test_await_context_second_review_like_tsc(src, name, expected):
    assert _calls(name, extract_from_tree_sitter(src, "x.ts", "typescript")) == expected


def test_constructor_key_continuation_and_accessors_like_tsc():
    src = 'class P { "con\\\nstructor"() { a(); } }\n' \
          'class N { *"constructor"() {} }\nclass M { get "constructor"() { return 1; } }\n' \
          'class Q { "\\u{110000}x"() {} }\n'
    names = {c.start_line: c.name for c in extract_from_tree_sitter(src, "x.ts", "typescript")
             if c.type == "method"}
    assert names[1] == "constructor"            # `\` + salto es continuación: "constructor"
    assert names[3] == '"constructor"' and names[4] == '"constructor"'
    assert 5 in names                           # escape fuera de rango: no revienta el archivo


def test_three_same_name_same_line_ids_unique_and_first_keeps_id():
    caps = extract_from_tree_sitter("namespace A.A.A { }\nconst o = { get x() { a(); }, set x(v) { b(); } };\n",
                                    "f.ts", "typescript")
    assert len({c.id for c in caps}) == len(caps)
    first_get = next(c for c in caps if c.name == "x" and "a" in c.calls)
    assert first_get.id == "f.ts:2:x"           # el primero en el texto conserva el id
