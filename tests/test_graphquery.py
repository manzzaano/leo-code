"""Tests del cerebro determinista: GraphQuery (where/who_calls/callees/impact/trace)
y boundary (aristas cross-lenguaje HTTP). Cero LLM, deterministas."""

from leo_code.core.parser import Capsule
from leo_code.core.graphquery import GraphQuery
from leo_code.core.boundary import link_http_edges, _norm


def _cap(name, calls=None, file="a.py", line=1, t="function", content="x", lang="python"):
    return Capsule(id=f"{file}:{name}", type=t, name=name, file_path=file, start_line=line,
                   end_line=line + 2, language=lang, signature=f"def {name}()",
                   content=content, calls=calls or [])


def _chain():
    return {c.id: c for c in [
        _cap("button", ["fetchUser"], "ui.tsx", 10, "component"),
        _cap("fetchUser", ["apiGetUser"], "ui.tsx", 20),
        _cap("apiGetUser", ["queryDb"], "api.py", 5),
        _cap("queryDb", ["usersTable"], "db.py", 30),
        _cap("usersTable", [], "db.py", 1, "model"),
    ]}


def test_where_cites_definition():
    g = GraphQuery(_chain())
    p = g.where("apiGetUser")
    assert p.found and p.cites[0].file == "api.py" and p.cites[0].line == 5


def test_who_calls():
    g = GraphQuery(_chain())
    assert {c.name for c in g.who_calls("apiGetUser").cites} == {"fetchUser"}


def test_callees():
    g = GraphQuery(_chain())
    assert {c.name for c in g.callees("apiGetUser").cites} == {"queryDb"}


def test_impact_transitive():
    g = GraphQuery(_chain())
    assert {c.name for c in g.impact("usersTable").cites} == {"queryDb", "apiGetUser", "fetchUser", "button"}


def test_trace_path_with_proof():
    g = GraphQuery(_chain())
    p = g.trace("button", "usersTable")
    assert [c.name for c in p.cites] == ["button", "fetchUser", "apiGetUser", "queryDb", "usersTable"]
    # cada salto citado en su archivo real (cross-archivo)
    files = {c.file for c in p.cites}
    assert {"ui.tsx", "api.py", "db.py"} <= files


def test_trace_no_hallucination():
    g = GraphQuery(_chain())
    assert not g.trace("usersTable", "button").found  # no hay camino → sin resultado


def test_resolve_prefers_def_over_import():
    caps = {
        "imp": _cap("foo", file="b.py", t="function", content=""),  # pseudo-import: sin content
        "def": _cap("foo", file="a.py", line=7, content="def foo(): return 1"),
    }
    caps["imp"].signature = "from a import foo"
    g = GraphQuery(caps)
    assert g.where("foo").cites[0].file == "a.py"  # cita la def, no el import


def test_norm_routes_match_across_languages():
    assert _norm("/api/users/${id}") == _norm("/api/users/{id}") == _norm("/api/users/:id")
    assert _norm("https://h/api/x?q=1") == "/api/x"


def test_boundary_links_http_edge():
    caps = {c.id: c for c in [
        _cap("UserBtn", file="ui.tsx", t="component", lang="ts",
             content="fetch('/api/users/${id}')"),
        _cap("get_user", ["q"], "api.py", t="endpoint",
             content="@app.get('/api/users/{id}')\ndef get_user(): return q()"),
        _cap("q", [], "db.py", t="model"),
    ]}
    assert link_http_edges(caps) == 1
    g = GraphQuery(caps)
    p = g.trace("UserBtn", "q")
    assert [c.name for c in p.cites] == ["UserBtn", "get_user", "q"]
    assert {c.file for c in p.cites} == {"ui.tsx", "api.py", "db.py"}  # cruza lenguajes


def _import_of(name, file):
    c = _cap(name, file=file, t="class", content="")
    c.signature = f"from pkg.models import {name}"
    return c


def test_where_hides_imports_when_the_definition_exists():
    # Antes: `where Capsule` daba 17 resultados (16 imports) y la dataclass salía 6ª.
    caps = [_import_of("Model", f"use{i}.py") for i in range(5)] + [_cap("Model", file="models.py", t="dataclass")]
    p = GraphQuery({c.id: c for c in caps}).where("Model")
    assert [c.file for c in p.cites] == ["models.py"]
    assert "imported in 5 files" in p.render()


def test_where_keeps_imports_of_an_external_symbol():
    # Sin definición indexada (p. ej. Path), los imports son lo único que se puede citar.
    caps = [_import_of("Path", "a.py"), _import_of("Path", "b.py")]
    assert len(GraphQuery({c.id: c for c in caps}).where("Path").cites) == 2


def test_where_lists_product_code_before_tests_and_benchmarks():
    caps = [_cap("main", file="benchmark/run.py"), _cap("main", file="tests/test_x.py"),
            _cap("main", file="pkg/cli.py")]
    assert GraphQuery({c.id: c for c in caps}).where("main").cites[0].file == "pkg/cli.py"


def test_where_names_the_class_of_a_method_and_shows_its_signature():
    a, b = _cap("search", file="bm25.py", t="method"), _cap("search", file="store.py", t="method")
    a.properties, b.properties = {"qualified": "BM25Index.search"}, {"qualified": "VectorStore.search"}
    a.signature = "def BM25Index.search(self, query, top_k) -> list"
    out = GraphQuery({a.id: a, b.id: b}).where("search").render()
    assert "BM25Index.search (method) @ bm25.py:1" in out and "VectorStore.search (method)" in out
    assert "def BM25Index.search(self, query, top_k) -> list" in out


def test_impact_says_through_whom_and_at_what_depth():
    p = GraphQuery(_chain()).impact("usersTable")
    fetch = next(c for c in p.cites if c.name == "fetchUser")
    assert "fetchUser (function) @ ui.tsx:20 ← via apiGetUser · depth 3" == str(fetch)
    assert "edges:" not in p.render()


def test_impact_stops_at_the_limit_and_says_so():
    caps = {c.id: c for c in [_cap("core", [], "core.py")]
            + [_cap(f"f{i}", ["core"], "svc.py", i * 10) for i in range(3)]
            + [_cap(f"test_{i}", ["core"], "tests/test_c.py", i * 10, "test") for i in range(3)]}
    p = GraphQuery(caps).impact("core", limit=4)
    assert len(p.cites) == 4
    assert "stopped at 4; more dependents exist" in p.render()
    assert "1 of them in tests/benchmarks" in p.render()


def test_callers_of_a_python_def_exclude_js_callers_of_a_homonym():
    caps = {c.id: c for c in [_cap("main", [], "m.py"),
                              _cap("main", [], "x.js", lang="javascript"),
                              _cap("boot", ["main"], "y.js", lang="javascript")]}
    g = GraphQuery(caps)
    assert g.callers_of_def(caps["m.py:main"]) == []
    assert [c.name for c in g.callers_of_def(caps["x.js:main"])] == ["boot"]


def test_resolve_memoized_keeps_definitions_first():
    # test_closure llama a _resolve 168k veces en django: sin memo pagaba un sort en cada una
    imp = Capsule(id="i", type="function", name="go", file_path="b.py", start_line=1, end_line=1,
                  language="python", signature="from a import go", content="go")
    fn = Capsule(id="f", type="function", name="go", file_path="a.py", start_line=1, end_line=1,
                 language="python", signature="def go()", content="def go(): ...")
    gq = GraphQuery({"i": imp, "f": fn})
    first = gq._resolve("go")
    assert [c.id for c in first] == ["f", "i"]
    assert gq._resolve("go") is first
    assert gq._resolve("externo") == [] and "externo" not in gq._resolved   # sin memo de nombres externos
