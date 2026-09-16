"""leo-mcp — servidor MCP (stdio) sobre el motor estructural de leo-code.

Dos tools:
  get_context — subgrafo AST relevante a una pregunta, cuerpos incluidos, comprimido.
  graph       — consultas deterministas al grafo de llamadas (where/who_calls/impact/
                trace/guard), citadas archivo:línea, cero LLM.

Registro (Claude Code):  claude mcp add leo-mcp -- npx -y leo-mcp

Todo lo que ve el agente/usuario va en inglés (estándar del ecosistema MCP); el
índice vive en la caché de usuario, nunca dentro del repo.
"""

import asyncio
import difflib
import importlib
import logging
import os
import re
import sys
import threading
from collections import Counter
from io import TextIOWrapper

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from leo_code import __version__, engine
from leo_code.core.boundary import link_http_edges
from leo_code.core.graphquery import GraphQuery, _bare
from leo_code.core.guardian import Guardian
from leo_code.core.tokens import count_tokens
from leo_code.logging_config import setup_logging

log = logging.getLogger("leo.mcp")

# Claude Code muestra las instructions aunque difiera las tools tras ToolSearch: es
# lo que decide si el agente las usa (adopción ~0 en M2 sin esto).
INSTRUCTIONS = """\
leo-mcp gives you this repository's real call graph, parsed from the AST (full AST for Python and TypeScript/JavaScript; approximate for Go, Java, Rust and others).
- To understand code (how X works, where to change Y, why Z fails), call get_context with the question before grepping or opening files: it returns the relevant symbols with their bodies, compressed.
- For structural facts use graph. It is exact and cites file:line: where (definition), who_calls (direct callers), impact (everything that transitively depends on a symbol), trace (call path from A to B, including frontend fetch -> backend route), guard (impact plus which dependents have no tests).
- Before changing a function's signature or behavior, run graph op=guard on it.
- The graph is static: calls through WebSockets, subprocesses, queues, reflection or string-built dispatch are not edges."""

server = Server("leo-mcp", version=__version__, instructions=INSTRUCTIONS)

_REPO_PROP = {"repo_path": {"type": "string",
                            "description": "Repository root. Defaults to the project the server was started in."}}

_TOOL = types.Tool(
    name="get_context",
    description=(
        "Code context for a question or task: the AST subgraph of the relevant symbols "
        "(signatures and bodies), compressed, with file:line. Use it before grep/read to "
        "understand how something works, where to make a change, or why something fails."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Question or task about the code, in natural language or a symbol name."},
            **_REPO_PROP,
            "task_type": {"type": "string", "default": "auto",
                          "description": "auto|code_query|refactor|debug|review|search|code_gen|optimize|audit"},
            "budget_tokens": {"type": "integer", "default": 0, "description": "Token cap (0 = automatic)."},
        },
        "required": ["query"],
    },
)

# op -> argumentos obligatorios (el JSON Schema no puede expresar "requerido según op").
_NEEDS = {"where": ("symbol",), "who_calls": ("symbol",), "impact": ("symbol",),
          "guard": ("symbol",), "trace": ("src", "dst")}
_GRAPH_OPS = tuple(_NEEDS)
_GRAPH_TOOL = types.Tool(
    name="graph",
    description=(
        "Deterministic call-graph query with file:line proof, no LLM. "
        "op=where: definition · who_calls: direct callers · impact: everything that transitively "
        "depends on the symbol (what breaks if you change it) · trace: call path src -> dst, "
        "crossing frontend fetch -> backend route · guard: impact plus which dependents have no tests. "
        "where/who_calls/impact/guard need `symbol`; trace needs `src` and `dst`."
    ),
    inputSchema={"type": "object", "properties": {
        "op": {"type": "string", "enum": list(_GRAPH_OPS)},
        "symbol": {"type": "string", "description": "Function, method or class name (where/who_calls/impact/guard)."},
        "src": {"type": "string", "description": "Start symbol (trace)."},
        "dst": {"type": "string", "description": "End symbol (trace)."},
        **_REPO_PROP},
        "required": ["op"]},
)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [_TOOL, _GRAPH_TOOL]


def _relativize(text: str, repo: str) -> str:
    """Citas con ruta relativa al repo: menos tokens y legible para el cliente MCP."""
    pref = repo.replace("\\", "/").rstrip("/") + "/"
    return text.replace("\\", "/").replace(pref, "")


def _repo(args: dict) -> str:
    """repo_path explícito > LEO_REPO > cwd del server (los clientes MCP lo lanzan en el proyecto)."""
    rp = (args.get("repo_path") or "").strip()
    if rp in ("", "."):
        rp = os.getenv("LEO_REPO") or "."
    repo = os.path.abspath(rp)
    if not os.path.isdir(repo):
        raise ValueError(f"repo_path is not a directory: {repo}")
    return repo


def _fmt_langs(by_language: dict) -> str:
    return " · ".join(f"{lang} {n:,}" for lang, n in list(by_language.items())[:4])


def _index(repo: str) -> None:
    """Índice al día + una línea a stderr cuando hubo trabajo (visible en los logs MCP del cliente)."""
    stats = engine.ensure_structural(repo)
    if stats:
        print(f"[leo-mcp] {stats['action']} {repo}: {stats['capsules']:,} symbols "
              f"({_fmt_langs(stats['by_language'])}) in {stats['seconds']}s", file=sys.stderr)


def _empty_msg(repo: str) -> str:
    from leo_code.rag.indexer import Indexer
    return (f"No indexable source files found in {repo}. leo-mcp parses: "
            f"{', '.join(Indexer.CODE_LANGUAGES)}. Dependencies, build output, minified "
            "bundles and files ignored by .gitignore are skipped.")


# Grafo por repo (solo sus cápsulas, con aristas HTTP cosidas); se reconstruye cuando
# el índice del repo cambia de generación.
_gq_cache: dict[str, tuple[int, dict, GraphQuery]] = {}


def _repo_graph(repo: str) -> tuple[dict, GraphQuery]:
    _index(repo)
    gen = engine.generation(repo)
    hit = _gq_cache.get(repo)
    if hit and hit[0] == gen:
        return hit[1], hit[2]
    caps = {c.id: c for c in engine._repo_caps(engine._get_indexer(), repo)}
    link_http_edges(caps)  # idempotente: no duplica aristas ya añadidas
    gq = GraphQuery(caps)
    _gq_cache[repo] = (gen, caps, gq)
    return caps, gq


def _known(gq: GraphQuery, s: str) -> bool:
    return bool(gq._resolve(s) or gq.callers.get(s) or gq.callers.get(_bare(s)))


# Recuperación in-band: símbolo desconocido → candidatos cercanos, para que el
# siguiente intento del agente sea otra llamada MCP y no una regresión a grep.
def _not_found(gq: GraphQuery, name: str) -> str:
    cands = difflib.get_close_matches(name, list(gq.by_name), n=5, cutoff=0.55)
    hint = ("Closest symbols: " + ", ".join(f"`{c}`" for c in cands) + ". Retry graph with one of them."
            if cands else f'Try get_context("{name}") for a text search.')
    return (f"Symbol '{name}' is not in the call graph. {hint} "
            "(Graph symbols are functions, methods, classes and Python module constants; "
            "class attributes, local variables and inline arrow functions are not.)")


# Siguiente paso sugerido por op: la respuesta dirige la próxima llamada MCP.
_NEXT = {
    "where": '[next] body and dependencies: get_context("<symbol>") · callers: graph op=who_calls',
    "who_calls": "[next] transitive dependents: graph op=impact · before editing: graph op=guard",
    "impact": "[next] which of these have tests: graph op=guard",
    "trace": '[next] body of any hop: get_context("<symbol>")',
    "guard": "[note] affected symbols WITHOUT tests are the real risk: review them or add tests before editing.",
}


_DEF_LINE = re.compile(r"\s*(export\s+)?(async\s+)?(def|function|class)\s")


def _who_calls(gq: GraphQuery, symbol: str) -> str:
    """who_calls con las líneas de LLAMADA, no solo la de definición del caller.

    Medido en el harness sobre NEXUS (2026-09-15): con `execute_batch @ executor_agent.py:32`
    los agentes contestaban "call site: línea 32" y perdían la 2ª llamada (:39, :55).
    Una cápsula (p.ej. la clase) cuyas llamadas ya cubre otra más estrecha (su método) se omite.
    Solo presentación: el grafo auditado (GraphQuery) no cambia.
    """
    bare = _bare(symbol)
    call = re.compile(rf"\b{re.escape(bare)}\s*(?:<[^()\n]*>)?\s*\(")
    callers = list({c.id: c for c in gq._callers_of(symbol)}.values())
    sites = {c.id: [c.start_line + i for i, text in enumerate((c.content or "").splitlines())
                    if call.search(text) and not _DEF_LINE.match(text)] for c in callers}
    kept, covered = [], set()
    for c in sorted(callers, key=lambda c: (c.end_line or 0) - (c.start_line or 0)):
        own = {(c.file_path, ln) for ln in sites[c.id]}
        if own and own <= covered:
            continue
        covered |= own
        kept.append(c)
    if not kept:
        return gq.who_calls(symbol).render()
    kept.sort(key=lambda c: (c.file_path, c.start_line))
    n_sites = len(covered)
    head = (f"[who_calls] {symbol} — {n_sites} call site(s) in {len(kept)} caller(s), with proof:"
            if n_sites else f"[who_calls] {symbol} — {len(kept)} caller(s), with proof:")
    lines = [head]
    for c in kept[:50]:
        at = (" → calls at " + ", ".join(f":{ln}" for ln in sites[c.id])) if sites[c.id] else ""
        lines.append(f"  · {c.name} ({c.type}) @ {c.file_path}:{c.start_line}{at}")
    return "\n".join(lines)


def _graph(args: dict) -> str:
    op = args.get("op")
    if op not in _NEEDS:
        raise ValueError(f"Invalid op {op!r}. Use one of: {', '.join(_GRAPH_OPS)}")
    missing = [k for k in _NEEDS[op] if not str(args.get(k) or "").strip()]
    if missing:
        raise ValueError(f"graph op={op} requires: {', '.join(missing)}")
    repo = _repo(args)
    caps, gq = _repo_graph(repo)
    if not caps:
        return _empty_msg(repo)
    syms = [args[k].strip() for k in _NEEDS[op]]
    unknown = [s for s in syms if not _known(gq, s)]
    if unknown:
        return "\n".join(_not_found(gq, s) for s in unknown)
    if op == "guard":
        # Guardian sobre las MISMAS cápsulas (boundary ya cosido por _repo_graph).
        out = Guardian(caps).review(syms[0]).render()
    elif op == "who_calls":
        out = _who_calls(gq, syms[0])
    else:
        proof = gq.trace(*syms) if op == "trace" else getattr(gq, op)(syms[0])
        out = proof.render()
        if op == "trace" and not proof.found:
            out += ("\n(No static call path. Hops through WebSockets, subprocesses, queues or "
                    "string-built dispatch are not followed, which can be why.)")
    return _relativize(out + "\n\n" + _NEXT[op], repo)


_raw_tok_cache: dict[tuple[str, float], int] = {}


def _raw_tokens(path: str) -> int:
    """Tokens del archivo crudo (lo que costaría leerlo): referencia del ahorro visible."""
    try:
        key = (path, os.path.getmtime(path))
        if key not in _raw_tok_cache:
            with open(path, encoding="utf-8", errors="replace") as f:
                _raw_tok_cache[key] = count_tokens(f.read())
        return _raw_tok_cache[key]
    except OSError:
        return 0


def _get_context(args: dict) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("get_context requires 'query'.")
    repo = _repo(args)
    task_type = args.get("task_type") or "auto"
    budget = int(args.get("budget_tokens") or 0)

    # Estructural inmediato + embedding en background → la primera respuesta llega en
    # segundos aunque el repo tenga 60k cápsulas.
    _index(repo)
    _embed_bg(repo)
    result = engine.compute_context(repo, query, task_type, budget, self_sufficient=True)
    if result.get("task_type") == "no_code":
        # Una llamada a get_context ES sobre código por definición; el clasificador
        # marca no_code con queries cortas en inglés y devolvía contexto VACÍO.
        result = engine.compute_context(repo, query, "code_query", budget, self_sufficient=True)
    if not result["capsules_total"]:
        return _empty_msg(repo)

    ctx = result["context"]
    # El compressor antepone "ARCHIVOS: <paths>": a un agente genérico esa lista al
    # INICIO le dispara un read por archivo (doble coste medido). Va al pie.
    files: list[str] = []
    if ctx.startswith("ARCHIVOS: "):
        line, _, ctx = ctx.partition("\n")
        files = [f for f in line[len("ARCHIVOS: "):].split(", ") if f]
        ctx = ctx.lstrip("\n")

    tok = count_tokens(ctx)
    raw = sum(_raw_tokens(f) for f in files)
    saving = (f" · the {len(files)} source files it draws from are ~{raw:,} tokens "
              f"(-{round(100 * (1 - tok / raw))}%)") if raw > tok else ""
    header = (f"[leo-mcp · {tok:,} tokens of code context{saving} · "
              f"{result['capsules_total']:,} symbols indexed]\n"
              "[Extracted from the AST: the relevant symbols with their bodies. Answer from this; "
              "don't re-read these files unless you need exact lines that are missing.]\n\n")
    sources = ("\n\n[sources already included: " + ", ".join(files) + "]") if files else ""
    footer = ('\n\n[more: get_context("<symbol>") for one symbol · graph for callers, impact, '
              "call paths and untested dependents]")
    return _relativize(header + ctx + sources + footer, repo)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Las excepciones las convierte el SDK en isError con el mensaje: ValueError legibles.
    if name == "graph":
        text = await asyncio.to_thread(_graph, arguments)
    elif name == "get_context":
        text = await asyncio.to_thread(_get_context, arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=text)]


# Repos cuyo embedding (semántico) ya se lanzó en background, para no duplicarlo.
_embed_started: set[str] = set()
_embed_lock = threading.Lock()


def _embed_bg(repo: str):
    """Embedding (recall semántico, extra opcional) en BACKGROUND: el motor ya sirve
    estructural desde el segundo uno. El encoder debe haberse importado antes en el
    hilo principal (torch deadlockea si se importa por primera vez en un worker en Windows)."""
    if not engine.SEMANTIC:
        return
    with _embed_lock:
        if repo in _embed_started:
            return
        _embed_started.add(repo)

    def _do():
        try:
            vs = engine._get_vector_store(repo)
            if vs.count() == 0:
                vs.add(engine._repo_caps(engine._get_indexer(), repo))
        except Exception as e:
            print(f"[leo-mcp] background embedding failed: {e}", file=sys.stderr)
            log.warning(f"embed bg fallo: {e}")

    threading.Thread(target=_do, daemon=True, name=f"embed:{repo[-20:]}").start()


def _is_project(repo: str) -> bool:
    """No precalentar $HOME ni la raíz del disco (cliente lanzado fuera de un proyecto)."""
    return repo != os.path.abspath(os.path.expanduser("~")) and os.path.dirname(repo) != repo


# Extensiones C que el servidor importa perezosamente. En Windows, el primer import de
# una de ellas dentro de un worker se cuelga mientras el hilo lector de stdin tiene un
# ReadFile síncrono pendiente sobre el pipe (medido 2026-09-15: 1ª get_context colgada
# en la instalación base, stack en numpy/_core/multiarray create_module vía rank_bm25).
# Se importan en el hilo principal ANTES de que el servidor empiece a leer stdin.
_PRELOAD = ("numpy", "rank_bm25", "orjson", "tree_sitter", "tree_sitter_typescript", "tree_sitter_javascript")


def _preload_native():
    for name in _PRELOAD + (("torch", "sentence_transformers") if engine.SEMANTIC else ()):
        try:
            importlib.import_module(name)
        except Exception as e:
            print(f"[leo-mcp] import {name} failed: {e}", file=sys.stderr)
            log.warning(f"preload {name} fallo: {e}")


def _warmup(repo: str):
    """Arranque sin bloquear el handshake MCP: índice y carga del modelo en background
    (los clientes matan el server si el handshake tarda). Los imports nativos ya los
    hizo _preload_native en el hilo principal."""

    def _bg():
        if _is_project(repo):
            try:
                _index(repo)
            except Exception as e:
                print(f"[leo-mcp] indexing {repo} failed: {e}", file=sys.stderr)
                log.warning(f"warmup index fallo: {e}")
            _embed_bg(repo)
        if engine.SEMANTIC:
            try:
                engine._get_vector_store(repo).search("warmup")  # carga el modelo
            except Exception as e:
                print(f"[leo-mcp] semantic warmup failed: {e}", file=sys.stderr)
                log.warning(f"warmup encoder fallo: {e}")

    threading.Thread(target=_bg, daemon=True, name="warmup-bg").start()


async def main():
    setup_logging(log_dir=engine._CACHE_DIR / "logs")
    # El canal MCP usa stdout. El indexer y otras libs hacen print() (en este y otros
    # threads) y eso corrompería el protocolo: stdout REAL para JSON-RPC, sys.stdout → stderr.
    protocol_stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
    sys.stdout = sys.stderr
    if os.getenv("LEO_DEBUG_DUMP"):  # diagnóstico: volcar stacks periódicamente a stderr
        import faulthandler
        faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
    _preload_native()
    _warmup(os.path.abspath(os.getenv("LEO_REPO") or "."))
    async with stdio_server(stdout=protocol_stdout) as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run_stdio():
    """Entrypoint síncrono para console_scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run_stdio()
