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
    monkeypatch.setattr(engine, "_synced_at", {})
    monkeypatch.setattr(engine, "_save_timers", {})
    # Escritura del índice síncrona: en producción va diferida (ver _schedule_save), y
    # estos tests comprueban el CONTENIDO de la caché, no cuándo se escribe. El diferido
    # tiene sus propios tests en test_deferred_save.py.
    monkeypatch.setattr(engine, "_SAVE_DEBOUNCE_S", 0.0)
    monkeypatch.setattr(mcp_server, "_gq_cache", {})
    monkeypatch.setattr(mcp_server, "_guard_cache", {})
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
    assert "Agent.run (method) @ agent.py:4 → calls at :5, :6" in out
    assert "other (function) @ agent.py:8 → calls at :9" in out
    assert "Agent (class)" not in out   # sus llamadas ya las cubre su método


_TWO_SAVES = ("class A:\n"                 # 1
              "    def save(self):\n"      # 2
              "        return 1\n"         # 3
              "class B:\n"                 # 4
              "    def save(self):\n"      # 5
              "        return 2\n"         # 6
              "def use_a():\n"             # 7
              "    a = A()\n"              # 8
              "    a.save()\n"             # 9
              "def use_b():\n"             # 10
              "    b = B()\n"              # 11
              "    b.save()\n"             # 12
              "def use_any(x):\n"          # 13
              "    x.save()\n"             # 14
              "def both():\n"              # 15
              "    a = A()\n"              # 16
              "    b = B()\n"              # 17
              "    a.save()\n"             # 18
              "    b.save()\n")            # 19


def test_who_calls_class_method_lists_only_callers_of_that_definition(fresh_engine, tmp_path):
    repo = _write(tmp_path / "svc" / "m.py", _TWO_SAVES).parent
    out = mcp_server._graph({"op": "who_calls", "symbol": "A.save", "repo_path": str(repo)})
    assert "use_a (function) @ m.py:7 → calls at :9" in out
    assert "use_any (function) @ m.py:13 → calls at :14" in out   # sin resolver: por nombre
    assert "both (function) @ m.py:15 → calls at :18\n" in out    # no la línea de b.save()
    assert "use_b" not in out


def test_who_calls_bare_name_with_homonyms_says_how_to_narrow(fresh_engine, tmp_path):
    repo = _write(tmp_path / "svc" / "m.py", _TWO_SAVES).parent
    out = mcp_server._graph({"op": "who_calls", "symbol": "save", "repo_path": str(repo)})
    assert "use_b (function)" in out and "use_a (function)" in out
    assert "2 definitions named save (A.save, B.save)" in out


def test_who_calls_puts_product_first_and_says_when_it_cuts(fresh_engine, tmp_path):
    _write(tmp_path / "svc" / "core.py", "def helper():\n    return 1\n"
                                         "def zz_main():\n    return helper()\n")
    _write(tmp_path / "svc" / "tests" / "test_h.py",
           "".join(f"def test_{i:02}():\n    helper()\n" for i in range(55)))
    out = mcp_server._graph({"op": "who_calls", "symbol": "helper", "repo_path": str(tmp_path / "svc")})
    lines = out.splitlines()
    assert lines[1].startswith("  · zz_main (function) @ core.py:3")
    assert "showing 50 of 56 callers (55 in tests/benchmarks)" in out


def test_who_calls_ignores_names_in_docstrings_and_comments(fresh_engine, tmp_path):
    repo = _write(tmp_path / "svc" / "m.py",
                  "def helper(x):\n"                      # 1
                  "    return x\n"                        # 2
                  "class Svc:\n"                          # 3
                  '    """Use helper(x) to do things."""\n'  # 4
                  "    def run(self):\n"                  # 5
                  "        # helper(2) is cheap\n"        # 6
                  "        return helper(1)\n").parent    # 7
    out = mcp_server._graph({"op": "who_calls", "symbol": "helper", "repo_path": str(repo)})
    assert "1 call site(s) in 1 caller(s)" in out
    assert "Svc.run (method) @ m.py:5 → calls at :7\n" in out


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


def test_get_context_says_so_when_nothing_matches(fresh_engine, tmp_path):
    # Antes: cabecera "0 tokens of code context" + "Answer from this" con cuerpo en blanco.
    repo = _write(tmp_path / "shop" / "app.py", "def compute_total(items):\n    return sum(items)\n").parent
    out = mcp_server._get_context({"query": "authentication flow", "repo_path": str(repo)})
    assert "no symbol matched" in out and "graph op=where" in out
    assert "Answer from this" not in out



def test_get_context_answers_with_code_when_query_reads_as_code_gen(fresh_engine, tmp_path):
    # "write" clasifica code_gen, cuya estrategia es solo el árbol de directorios (y apunta
    # a search_code, tool del agente antiguo): por MCP get_context devuelve código siempre.
    repo = _write(tmp_path / "shop" / "app.py",
                  "def write_invoice(order):\n    return format_total(order)\n").parent
    out = mcp_server._get_context({"query": "how does write_invoice write the invoice", "repo_path": str(repo)})
    assert "def write_invoice" in out
    assert "search_code" not in out and "Estructura del repositorio" not in out


def test_get_context_labels_are_english(fresh_engine, tmp_path):
    # El agente recibía "Tipo Retorno", "Parametros", "[LLAMA]" y "[truncado]".
    body = "\n".join(f"    x{i} = helper({i})" for i in range(400))
    repo = _write(tmp_path / "shop" / "app.py",
                  "def helper(n: int) -> int:\n    return n\n\n\n"
                  f"def compute_total(items: list) -> int:\n{body}\n    return 0\n").parent
    out = mcp_server._get_context({"query": "compute_total", "repo_path": str(repo)})
    assert "compute_total" in out
    for spanish in ("Tipo Retorno", "Parametros", "[LLAMA]", "[truncado]", "Lineas"):
        assert spanish not in out, spanish

def test_codex_snippet_is_valid_toml(capsys, tmp_path):
    # Codex no está instalado aquí: al menos el TOML que imprimimos debe parsear.
    import tomllib
    from argparse import Namespace
    from leo_code import cli
    assert cli.cmd_init(Namespace(client="codex", repo=str(tmp_path))) == 0
    body = capsys.readouterr().out.split("\n", 1)[1]
    parsed = tomllib.loads(body)
    srv = parsed["mcp_servers"]["leo-mcp"]
    assert srv["command"]
    # installed binary (command = .../leo-mcp) or uvx from the repo (args end in leo-mcp)
    assert "leo-mcp" in " ".join([srv["command"], *srv["args"]])


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


def test_trace_to_an_external_symbol_says_it_is_not_in_the_repo(fresh_engine, tmp_path):
    repo = _write(tmp_path / "svc" / "m.py",
                  "def fetch_all(client):\n    return client.fetch_page('x')\n").parent
    out = mcp_server._graph({"op": "trace", "src": "fetch_all", "dst": "fetch_page", "repo_path": str(repo)})
    assert "`fetch_page` has no definition in this repo" in out
    assert "No static call path" not in out


def test_guard_reuses_guardian_until_index_changes(fresh_engine, fullstack, monkeypatch):
    # Guardian(caps) se construía en CADA llamada: django 11-18 s por guard.
    built = []
    real = mcp_server.Guardian
    monkeypatch.setattr(mcp_server, "Guardian", lambda caps: built.append(1) or real(caps))
    args = {"op": "guard", "symbol": "get_session", "repo_path": str(fullstack)}
    first = mcp_server._graph(args)
    assert mcp_server._graph(args) == first and len(built) == 1
    engine._generation[str(fullstack)] = engine.generation(str(fullstack)) + 1
    mcp_server._graph(args)
    assert len(built) == 2


def test_guardian_viejo_se_suelta_antes_de_construir_el_nuevo(monkeypatch):
    # Dos Guardian vivos a la vez eran el pico de RAM tras una edición (512 MB en django)
    from leo_code.server import mcp_server as M
    monkeypatch.setattr(M, "_guard_cache", {"r": ({}, object())})
    vivos = []
    monkeypatch.setattr(M, "Guardian", lambda caps: vivos.append("r" in M._guard_cache) or object())
    M._guardian("r", {"nuevo": 1})
    assert vivos == [False]
