"""#9: lo que el parser TS/JS no veía: `new` y JSX como aristas, campos y asignaciones de
función, y tipos como símbolos sin aristas."""

import pytest

pytest.importorskip("tree_sitter_typescript")

from leo_code.core.graphquery import GraphQuery, rough_lines
from leo_code.core.guardian import Guardian
from leo_code.core.parser_ts import extract_from_tree_sitter


def _ex(src, path="x.ts", lang="typescript"):
    return extract_from_tree_sitter(src, path, lang)


def _one(name, caps):
    return next(c for c in caps if c.name == name)


def _gq(caps):
    return GraphQuery({c.id: c for c in caps})


# --- A: `new` y JSX ---

def test_new_is_an_edge():
    caps = _ex("class Foo {}\nfunction f(){ new Foo(); new ns.Bar<T>(1); return new (g())(); }")
    assert {"Foo", "Bar", "g"} == set(_one("f", caps).calls)


def test_class_built_with_new_has_dependents():
    caps = _ex("class Foo {}\nfunction f(){ return new Foo(); }\nfunction h(){ return f(); }")
    assert [c.name for c in _gq(caps).impact("Foo").cites] == ["f", "h"]


def test_jsx_component_is_an_edge_and_html_tag_is_not():
    src = "const Page = () => <div><Card x={1}/><ui.Modal></ui.Modal><motion.div/></div>;"
    assert set(_one("Page", _ex(src, "x.tsx")).calls) == {"Card", "Modal"}


def test_jsx_in_javascript():
    src = "function Page(){ return <Card/>; }"
    assert _one("Page", _ex(src, "x.jsx", "javascript")).calls == ["Card"]


def test_jsx_call_site_line():
    caps = _ex("function Page() {\n  return (\n    <Card/>\n  );\n}", "x.tsx")
    assert rough_lines(_one("Page", caps), "Card") == [3]


# --- D: funciones en campos y asignaciones ---

def test_class_field_with_function_is_a_symbol():
    caps = _ex("class C {\n  onClick = () => { go(); };\n  #priv = function () { hid(); };\n  n = 1;\n}")
    assert _one("onClick", caps).calls == ["go"] and _one("onClick", caps).type == "method"
    assert _one("#priv", caps).calls == ["hid"]
    assert not [c for c in caps if c.name == "n"]


def test_js_class_field_with_function_is_a_symbol():
    caps = _ex("class C { handle = () => go(); }", "x.js", "javascript")
    assert _one("handle", caps).calls == ["go"]


def test_assigned_function_is_a_symbol():
    src = ("a.b = function () { one(); };\nFoo.prototype.m = () => two();\nexports.e = () => three();\n"
           "module.exports = function () { four(); };\nx.y = 1;\n")
    names = {c.name: c.calls for c in _ex(src, "x.js", "javascript")}
    assert names == {"b": ["one"], "m": ["two"], "e": ["three"]}   # `exports` no es un nombre


# --- E1: tipos como símbolos, sin aristas ---

TYPES = """\
export interface Props { a: string }
type Id = string;
enum Color { Red }
namespace NS { export const x = 1; }
declare module "pkg" { export const y: number; }
"""


def test_types_are_symbols_without_edges():
    caps = _ex(TYPES)
    assert {c.name for c in caps} == {"Props", "Id", "Color", "NS"}
    assert all(c.type == "type_def" and c.calls == [] for c in caps)


def test_where_finds_a_type():
    assert _gq(_ex(TYPES)).where("Props").cites[0].line == 1


def test_guard_on_a_type_does_not_claim_safety():
    caps = _ex(TYPES + "function use(p: Props){}\n")
    out = Guardian({c.id: c for c in caps}).review("Props").render()
    assert "breaks nothing" not in out and "not modeled" in out


def test_impact_on_a_type_warns():
    assert "not modeled" in _gq(_ex(TYPES)).impact("Props").render()


def test_type_sharing_a_name_keeps_call_edges():
    caps = _ex("interface Foo {}\nclass Foo {}\nfunction f(){ return new Foo(); }")
    gq = _gq(caps)
    assert [c.name for c in gq.impact("Foo").cites] == ["f"]
    assert "not modeled" in gq.impact("Foo").note


def test_type_is_never_a_call_target():
    caps = _ex("interface run {}\nfunction a(){ run(); }")
    gq = _gq(caps)
    assert gq.callees("a").cites == []
    assert not gq.trace("a", "run").found


def test_context_prefers_the_exact_case_of_a_type(tmp_path):
    from leo_code.engine import _get_indexer, compute_context
    for i in range(8):
        (tmp_path / f"a{i}.ts").write_text(f"class G{i} {{ canActivate() {{ return true; }} }}\n", encoding="utf-8")
    (tmp_path / "z.ts").write_text("export interface CanActivate { marker_ok: boolean }\n", encoding="utf-8")
    _get_indexer().build(str(tmp_path), languages=["typescript"])
    assert "marker_ok" in compute_context(str(tmp_path), "CanActivate", task_type_in="code_query")["context"]
