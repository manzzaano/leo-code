"""Tests del guardián determinista: radio de explosión + cobertura + cross-lenguaje.
Cero LLM, deterministas."""

from leo_code.core.parser import Capsule
from leo_code.core.boundary import link_http_edges
from leo_code.core.guardian import Guardian


def _cap(name, content="x", file="a.py", line=1, t="function", calls=None, lang="python"):
    return Capsule(id=f"{file}:{name}", type=t, name=name, file_path=file, start_line=line,
                   end_line=line + 5, language=lang, signature="", content=content, calls=calls or [])


def _graph():
    caps = {c.id: c for c in [
        _cap("Dashboard", "fetch('/api/report')", "web/app.tsx", t="component", lang="ts"),
        _cap("get_report", "@app.get('/api/report')", "api.py", t="endpoint", calls=["build"]),
        _cap("build", file="logic.py", calls=["read_db"]),
        _cap("read_db", file="db.py", t="model"),
        _cap("test_build", file="tests/test_logic.py", t="test", calls=["build"]),
    ]}
    link_http_edges(caps)
    return caps


def test_coverage_closure():
    g = Guardian(_graph())
    assert g.is_covered("build") and g.is_covered("read_db")     # alcanzados por test_build
    assert not g.is_covered("get_report") and not g.is_covered("Dashboard")


def test_blast_radius_crosses_language():
    g = Guardian(_graph())
    rep = g.review("get_report")
    names = {a.cite.name for a in rep.affected}
    assert "Dashboard" in names                                  # cruzó el límite HTTP


def test_uncovered_flagged_as_risk():
    g = Guardian(_graph())
    rep = g.review("get_report")
    dash = next(a for a in rep.affected if a.cite.name == "Dashboard")
    assert not dash.covered and len(rep.uncovered) >= 1


def test_covered_caller_not_flagged():
    g = Guardian(_graph())
    rep = g.review("read_db")
    build = next(a for a in rep.affected if a.cite.name == "build")
    assert build.covered                                          # build tiene test → cubierto


def test_diff_maps_to_changed_symbols():
    g = Guardian(_graph())
    diff = (
        "diff --git a/logic.py b/logic.py\n"
        "--- a/logic.py\n+++ b/logic.py\n"
        "@@ -1,3 +1,4 @@\n def build():\n+    pass\n"
    )
    syms = g.changed_symbols(diff)
    assert "build" in syms

    rep = g.review_diff(diff)
    assert any(r.symbol == "build" for r in rep)


def test_proof_is_citable():
    g = Guardian(_graph())
    rep = g.review("read_db")
    a = rep.affected[0]
    assert a.cite.file and a.cite.line >= 1 and a.cite.name      # archivo:línea presente
