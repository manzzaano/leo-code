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
