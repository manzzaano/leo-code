"""Regresión de leo-mcp como producto (auditoría M3, 2026-09-15): lo que un usuario
externo se encontraba roto — solo Python vía MCP, índice no persistido, grafo mezclando
repos, caché dentro del repo, KeyError pelados, bundles minificados en el grafo."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from leo_code import engine
from leo_code.rag.indexer import Indexer
from leo_code.server import mcp_server


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def fresh_engine(tmp_path, monkeypatch):
    """Engine como en un proceso nuevo, con la caché en tmp."""
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    monkeypatch.setattr(engine, "_generation", {})
    monkeypatch.setattr(mcp_server, "_gq_cache", {})
    monkeypatch.setattr(engine, "SEMANTIC", False)
    return tmp_path


@pytest.fixture
def fullstack(tmp_path):
    repo = tmp_path / "app"
    _write(repo / "backend" / "api.py",
           "from fastapi import FastAPI\napp = FastAPI()\n\n"
           "def get_session():\n    return 1\n\n"
           "@app.get(\"/api/jobs\")\ndef jobs():\n    return get_session()\n")
    _write(repo / "web" / "page.tsx",
           "export function JobsTable() {\n  loadJobs();\n  return <div/>;\n}\n\n"
           "function loadJobs() {\n  return fetch(\"/api/jobs\");\n}\n")
    _write(repo / ".next" / "static" / "chunk.js", "function leakedBuild() { return 1; }\n")
    _write(repo / "vendor.bundle.js", "function minified(){" + "var a=1;" * 200 + "}\n")
    return repo


def test_product_indexer_sees_tsx_and_skips_build_output_and_bundles(fullstack):
    idx = Indexer(hygiene=True)
    idx.build(str(fullstack))
    caps = idx.get_capsules().values()
    names = {c.name for c in caps}
    assert {"get_session", "jobs", "JobsTable", "loadJobs"} <= names
    assert {"python", "typescript"} <= {c.language for c in caps}
    assert "leakedBuild" not in names and "minified" not in names


def test_typescript_arrow_functions_are_symbols(tmp_path):
    # TS/JS real declara funciones como variables u objetos; sin esto un frontend React
    # no tenía símbolos. Los envoltorios que devuelven un VALOR no cuentan.
    from leo_code.core.parser import extract_from_file
    f = _write(tmp_path / "ui.tsx",
               "export const api = { jobs: () => get('/api/jobs') };\n"          # 1
               "const load = useCallback(async () => { await api.jobs(); }, []);\n"  # 2
               "export const Panel = () => { load(); return null; };\n"          # 3
               "const helper = function () { return inner(); };\n"               # 4
               "const first = items.findIndex((t) => t.id === 1);\n"             # 5
               "const memoised = useMemo(() => heavy(), []);\n")                 # 6
    caps = {c.name: c for c in extract_from_file(str(f), "typescript")}
    assert {"jobs", "load", "Panel", "helper"} <= set(caps)
    assert "first" not in caps and "memoised" not in caps  # son valores, no funciones
    assert "get" in caps["jobs"].calls and "jobs" in caps["load"].calls


def test_class_attributes_are_searchable_symbols(tmp_path):
    from leo_code.core.parser import extract_from_file
    f = _write(tmp_path / "config.py",
               "class Settings:\n    min_match_score: int = 60\n    debug = False\n")
    attrs = {c.name: c for c in extract_from_file(str(f), "python") if c.type == "attribute"}
    assert set(attrs) == {"min_match_score", "debug"}
    assert attrs["min_match_score"].start_line == 2
    assert attrs["min_match_score"].properties["qualified"] == "Settings.min_match_score"
    assert not attrs["min_match_score"].calls   # no añade aristas al grafo auditado


def test_files_without_capsules_are_not_reparsed_every_sync(tmp_path):
    empty = _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "code.py", "def f():\n    return 1\n")
    idx = Indexer(hygiene=True)
    idx.build(str(tmp_path))
    mtime = os.path.getmtime(empty)
    assert idx.sync(str(tmp_path), since_mtime=mtime + 1)["new"] == 1   # 1ª vez lo mira
    assert idx.sync(str(tmp_path), since_mtime=mtime + 1)["new"] == 0   # ya recordado
    empty.write_text("def later():\n    return 2\n", encoding="utf-8")
    assert idx.sync(str(tmp_path), since_mtime=mtime)["reparsed_capsules"] >= 1


def test_rebuild_of_emptied_repo_drops_old_capsules(tmp_path):
    f = _write(tmp_path / "a.py", "def gone():\n    return 1\n")
    idx = Indexer(hygiene=True)
    idx.build(str(tmp_path))
    f.unlink()
    assert idx.build(str(tmp_path)) == 0
    assert not idx.get_capsules()


def test_graph_crosses_python_and_tsx_via_http(fresh_engine, fullstack):
    out = mcp_server._graph({"op": "trace", "src": "JobsTable", "dst": "get_session",
                             "repo_path": str(fullstack)})
    assert "web/page.tsx" in out and "backend/api.py" in out
    assert str(fullstack) not in out.replace("\\", "/")  # citas relativas


def test_same_name_in_another_language_is_not_a_caller(tmp_path):
    from leo_code.core.graphquery import GraphQuery
    _write(tmp_path / "svc.py", "def read_config(d):\n    return d.get('k')\n")
    _write(tmp_path / "api.ts", "export function get(path: string) {\n  return fetch(path);\n}\n"
                                "export function loadJobs() {\n  return get('/api/jobs');\n}\n")
    idx = Indexer(hygiene=True)
    idx.build(str(tmp_path))
    gq = GraphQuery(idx.get_capsules())
    callers = {c.name for c in gq.who_calls("get").cites}
    assert callers == {"loadJobs"}            # dict.get() de Python no cuenta
    assert "read_config" not in {c.name for c in gq.impact("get").cites}


def test_who_calls_cites_call_lines_not_just_the_caller_definition(fresh_engine, tmp_path):
    repo = _write(tmp_path / "svc" / "agent.py",
                  "def get_session():\n"          # 1
                  "    return 1\n"                # 2
                  "class Agent:\n"                # 3
                  "    def run(self):\n"          # 4
                  "        x = get_session()\n"   # 5
                  "        y = get_session()\n"   # 6
                  "        return x, y\n"         # 7
                  "def other():\n"                # 8
                  "    return get_session()\n").parent  # 9
    out = mcp_server._graph({"op": "who_calls", "symbol": "get_session", "repo_path": str(repo)})
    assert "3 call site(s)" in out
    assert "run (method) @ agent.py:4 → calls at :5, :6" in out
    assert "other (function) @ agent.py:8 → calls at :9" in out
    assert "Agent (class)" not in out   # sus llamadas ya las cubre su método


def test_index_persists_and_resyncs(fresh_engine, fullstack, monkeypatch):
    repo = str(fullstack)
    assert engine.ensure_structural(repo)["action"] == "build"
    # "reinicio": proceso nuevo con la misma caché → carga, no re-parsea
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    assert engine.ensure_structural(repo)["action"] == "load"
    # edición durante la sesión → visible tras el throttle de resync
    gen = engine.generation(repo)
    _write(fullstack / "backend" / "extra.py", "def added_later():\n    return 2\n")
    engine._structural_at[repo] = 0.0
    assert engine.ensure_structural(repo) is not None
    assert engine.generation(repo) > gen
    assert "added_later" in mcp_server._graph({"op": "where", "symbol": "added_later", "repo_path": repo})


def test_graph_is_scoped_to_the_requested_repo(fresh_engine, tmp_path):
    a = _write(tmp_path / "repo_a" / "a.py", "def only_in_a():\n    return 1\n").parent
    b = _write(tmp_path / "repo_b" / "b.py", "def only_in_b():\n    return 2\n").parent
    assert "only_in_b" in mcp_server._graph({"op": "where", "symbol": "only_in_b", "repo_path": str(b)})
    out = mcp_server._graph({"op": "where", "symbol": "only_in_b", "repo_path": str(a)})
    assert "not in the call graph" in out


def test_friendly_errors_instead_of_keyerror(fresh_engine, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="requires: dst"):
        mcp_server._graph({"op": "trace", "src": "x", "repo_path": str(tmp_path)})
    with pytest.raises(ValueError, match="not a directory"):
        mcp_server._graph({"op": "where", "symbol": "x", "repo_path": str(tmp_path / "nope")})
    with pytest.raises(ValueError, match="requires 'query'"):
        mcp_server._get_context({"query": "  "})
    # sin repo_path: LEO_REPO manda sobre el cwd
    monkeypatch.setenv("LEO_REPO", str(tmp_path))
    assert mcp_server._repo({"repo_path": "."}) == os.path.abspath(tmp_path)


def test_short_acronyms_count_only_when_they_discriminate(tmp_path):
    from leo_code.core.parser import Capsule
    caps = {}
    for i, (name, path) in enumerate([("CVMorpher", "cv_morpher.py"), ("generate", "cv_morpher.py"),
                                      ("run_migrations", "env.py"), ("run_cycle", "main.py"),
                                      ("run_worker", "worker.py")]):
        caps[str(i)] = Capsule(id=str(i), type="function", name=name, file_path=str(tmp_path / path),
                               start_line=1, end_line=2, language="python", signature="", content="")
    # "cv" señala un archivo → cuenta; "run" aparece en tres → no señala nada concreto
    assert engine.discriminant_short_words({"cv", "run"}, caps) == {"cv"}


def test_context_leads_with_code_and_matches_short_acronyms(fresh_engine, tmp_path):
    repo = tmp_path / "app"
    _write(repo / "pdf_factory.py", '"""Renders CV data to PDF."""\nimport io\n\n\nclass PDFFactory:\n'
                                    "    def render(self):\n        return io.BytesIO()\n")
    _write(repo / "cv_morpher.py", "from pdf_factory import PDFFactory\n\n\nclass CVMorpher:\n"
                                   "    def generate(self, job):\n        return PDFFactory().render()\n")
    out = mcp_server._get_context({"query": "How does CV tailoring work?", "repo_path": str(repo)})
    body = out.split("\n\n", 2)[-1]
    assert "CVMorpher" in body.split("[sources")[0]
    assert not body.lstrip().startswith(("[pdf_factory", "[cv_morpher.__header__"))


def test_index_cache_is_invalidated_when_the_parser_changes(fresh_engine, fullstack, monkeypatch):
    repo = str(fullstack)
    engine.ensure_structural(repo)
    old = engine.repo_index_path(repo)
    assert old.exists()
    monkeypatch.setattr(engine, "_INDEX_FORMAT", engine._INDEX_FORMAT + 1)
    monkeypatch.setattr(engine, "_structural_at", {})
    assert engine.ensure_structural(repo)["action"] == "build"   # no reusa la caché vieja


def test_get_context_without_semantic_extra(fresh_engine, fullstack):
    assert isinstance(engine._get_vector_store(str(fullstack)), engine._NoVectorStore)
    out = mcp_server._get_context({"query": "how are jobs loaded from the api", "repo_path": str(fullstack)})
    assert out.startswith("[leo-mcp ·") and "jobs" in out


def test_codex_snippet_is_valid_toml(capsys, tmp_path):
    # Codex no está instalado aquí: al menos el TOML que imprimimos debe parsear.
    import tomllib
    from argparse import Namespace
    from leo_code import cli
    assert cli.cmd_init(Namespace(client="codex", repo=str(tmp_path))) == 0
    body = capsys.readouterr().out.split("\n", 1)[1]
    parsed = tomllib.loads(body)
    assert parsed["mcp_servers"]["leo-mcp"]["command"]
    assert "leo-mcp" in parsed["mcp_servers"]["leo-mcp"]["args"]


def test_python_and_npm_versions_match():
    import json
    import tomllib
    from leo_code import __version__
    root = Path(__file__).resolve().parents[1]
    py = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    npm = json.loads((root / "npm" / "package.json").read_text(encoding="utf-8"))["version"]
    assert py == npm == __version__  # el launcher npm pide leo-mcp==<su versión> a PyPI


def test_importing_engine_does_not_write_into_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "LEO_CACHE_DIR"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    subprocess.run([sys.executable, "-c", "import leo_code.server.mcp_server"],
                   cwd=tmp_path, env=env, check=True, capture_output=True)
    assert list(tmp_path.iterdir()) == []
