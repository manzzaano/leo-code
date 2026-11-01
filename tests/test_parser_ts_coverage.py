"""#9: lo que el parser TS/JS no veía: `new` y JSX como aristas, campos y asignaciones de
función, y tipos como símbolos sin aristas."""

import pytest

pytest.importorskip("tree_sitter_typescript")

from leo_code.core.graphquery import GraphQuery, rough_lines
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
