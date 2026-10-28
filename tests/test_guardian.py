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


def test_is_test_same_rule_as_hook():
    # Producto con «test» en el nombre del archivo NO es un test (django: testing.py,
    # testserver.py): antes contaba como test y lo que llamaba salía cubierto.
    for f in ("pkg/testing.py", "cmd/testserver.py", "cmd/sendtestemail.py", "pkg/latest.py"):
        assert not Guardian._is_test(_cap("helper", file=f)), f
    # Tests de verdad, incluido el `tests.py` de una app Django fuera de tests/.
    for f in ("tests/x.py", "pkg/test_x.py", "pkg/x_test.py", "scripts/tests.py", "web/a.test.ts"):
        assert Guardian._is_test(_cap("helper", file=f)), f


def test_coverage_by_definition_not_by_name(tmp_path):
    # Dos `helper` homónimos: el test solo llama al de a.py. Por nombre ambos salían
    # cubiertos; por definición, solo el que el test alcanza.
    from leo_code.rag.indexer import Indexer
    (tmp_path / "a.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "b.py").write_text("def helper():\n    return 2\n")
    (tmp_path / "c.py").write_text("from b import helper\n\ndef use_b():\n    return helper()\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "from a import helper\n\ndef test_h():\n    assert helper() == 1\n")
    idx = Indexer(); idx.build(str(tmp_path), verbose=False)
    g = Guardian(idx.get_capsules())
    defs = {c.file_path.replace("\\", "/").rsplit("/", 1)[-1]: c
            for c in g.gq.defs_named("helper")}
    assert g.is_covered(defs["a.py"]) and not g.is_covered(defs["b.py"])
    assert g.is_covered("helper")                    # por nombre: alguna def cubierta
    rep = g.review("use_b")
    assert not rep.changed_covered


def _repo_caps(tmp_path, files):
    from leo_code.rag.indexer import Indexer
    for name, src in files.items():
        (tmp_path / name).write_text(src)
    idx = Indexer(); idx.build(str(tmp_path), verbose=False)
    return idx.get_capsules()


def test_import_does_not_make_every_function_a_dependent(tmp_path):
    # Antes la parte (2) de augment_refs repartía lo referenciado a nivel de módulo entre
    # TODAS las funciones del archivo: en leo-code, impact 0 → guard 643 (`_detect_jsts`).
    caps = _repo_caps(tmp_path, {
        "b.py": "def target():\n    return 1\n",
        "a.py": ("import b\n\nHANDLER = b.target\n\n"
                 "def f1():\n    return 1\n\ndef f2():\n    return 2\n"),
    })
    names = {a.cite.name for a in Guardian(caps).review("target").affected}
    assert not names & {"f1", "f2"}, names


def test_dispatch_table_still_reaches_its_user(tmp_path):
    # Dispatch por dict a nivel de módulo: quien usa la tabla depende de sus funciones.
    caps = _repo_caps(tmp_path, {
        "b.py": "def target():\n    return 1\n",
        "a.py": ("import b\n\n_TABLE = {'go': b.target}\n\n"
                 "def run(k):\n    return _TABLE[k]()\n\ndef other():\n    return 2\n"),
    })
    names = {a.cite.name for a in Guardian(caps).review("target").affected}
    assert "run" in names and "other" not in names, names


def test_tests_are_coverage_not_risk_and_cut_is_announced():
    # 86% de los «✗ NO test» eran tests (nada cubre a un test). Ahora un test dependiente
    # cuenta como cobertura; el riesgo lista solo producto, y un corte se anuncia.
    caps = {c.id: c for c in
            [_cap("core", file="lib.py")]
            + [_cap(f"use{i}", file="app.py", line=10 * i, calls=["core"]) for i in range(45)]
            + [_cap("test_core", file="tests/test_lib.py", t="test", calls=["core"])]}
    rep = Guardian(caps).review("core")
    assert [a.cite.name for a in rep.uncovered if a.cite.name.startswith("test")] == []
    assert len(rep.uncovered) == 45
    out = rep.render()
    assert "1 test(s)" in out and "45 with NO test" in out
    assert "test_core (test)" not in out
    assert "showing 40 of 45" in out


def test_impact_cut_is_announced_and_cli_counts_unique():
    caps = {c.id: c for c in
            [_cap("core", file="lib.py"), _cap("core2", file="lib2.py")]
            + [_cap(f"use{i}", file="app.py", line=10 * i, calls=["core", "core2"]) for i in range(5)]}
    g = Guardian(caps)
    assert "stopped at 3" in g.review("core", limit=3).render()
    from leo_code.core.guardian import summarize
    reps = g.review_many(["core", "core2"])          # mismos 5 dependientes para los dos
    assert summarize(reps)["uncovered_risk"] == 5
