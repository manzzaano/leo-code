"""Servidor MCP (stdio) que expone el motor de contexto KC-RAG como una tool.

Esto es la mitad "vía MCP" del producto: cualquier agente MCP — Claude Code,
opencode, Cursor — lo añade y obtiene el subgrafo de código COMPRIMIDO en vez de
leer archivos enteros, gastando ~80% menos tokens con la misma señal.

Reusa exactamente el mismo retrieval+compress que el endpoint HTTP /context
(`compute_context`), así no hay drift entre ambos caminos.

Registro en el cliente MCP (ej. Claude Code `.mcp.json` u opencode):

    {
      "mcpServers": {
        "leo-code": {
          "command": "python",
          "args": ["-m", "leo_code.server.mcp_server"]
        }
      }
    }

ponytail: una sola tool (get_context). Las demás (search/index) se añaden cuando
un cliente real las pida; YAGNI hasta entonces.
"""

import asyncio
import os
import sys
import threading
from io import TextIOWrapper

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from leo_code.engine import (
    compute_context, _indexed_repos, _index_lock,
    _get_indexer, _get_vector_store, _repo_caps, _load_index_from_disk,
)
from leo_code.core.graphquery import GraphQuery
from leo_code.core.boundary import link_http_edges
from leo_code.core.guardian import Guardian

server = Server("leo-code")

# GraphQuery cacheado por repo (cerebro determinista; se reconstruye si crece el índice).
_gq_cache: dict[str, tuple[int, GraphQuery]] = {}


def _graphquery(repo: str) -> GraphQuery:
    """GraphQuery sobre el índice estructural del repo, con aristas cross-lenguaje
    (HTTP) ya cosidas. Determinista, cero LLM."""
    _ensure_structural(repo)
    caps = _get_indexer().get_capsules()
    cached = _gq_cache.get(repo)
    if cached and cached[0] == len(caps):
        return cached[1]
    link_http_edges(caps)  # idempotente: no duplica aristas ya añadidas
    gq = GraphQuery(caps)
    _gq_cache[repo] = (len(caps), gq)
    return gq

# Repos cuyo embedding (semántico) ya se lanzó en background, para no duplicarlo.
_embed_started: set[str] = set()
_embed_lock = threading.Lock()


def _ensure_structural(repo: str):
    """Índice estructural listo (parse AST, ~2000 cápsulas/s). Es lo único que el
    retrieval estructural necesita; ya da ~80% de reducción y recall del símbolo
    nombrado SIN embeddings. Rápido incluso en repos de 500k+ LOC (~30s)."""
    with _index_lock:
        if repo in _indexed_repos:
            return
        idx = _get_indexer()
        _load_index_from_disk()
        idx.build(repo)
        _indexed_repos.add(repo)


def _embed_bg(repo: str):
    """Lanza el embedding (recall semántico) en BACKGROUND. No bloquea: en un
    monorepo de 60k cápsulas embeber tarda ~4 min, pero el motor ya sirve estructural
    desde el segundo uno. El encoder debe haberse cargado antes en el hilo principal
    (torch deadlockea si se importa por primera vez en un worker thread en Windows)."""
    with _embed_lock:
        if repo in _embed_started:
            return
        _embed_started.add(repo)

    def _do():
        try:
            vs = _get_vector_store(repo)
            if vs.count() == 0:
                vs.add(_repo_caps(_get_indexer(), repo))
        except Exception as e:
            print(f"[leo-mcp] embed bg fallo: {e}", file=sys.stderr)

    threading.Thread(target=_do, daemon=True, name=f"embed:{repo[-20:]}").start()

_TOOL = types.Tool(
    name="get_context",
    description=(
        "Devuelve el subgrafo de codigo relevante y COMPRIMIDO para una consulta "
        "(funciones/clases con sus dependencias directas, extraido del AST), en vez "
        "del archivo entero. USALO ANTES de leer archivos con tus tools de fichero: "
        "ahorra ~80% de tokens manteniendo la senal. Ideal para preguntas sobre "
        "simbolos, refactors, code review, debugging y trazas cross-file."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "La pregunta o tarea sobre el codigo."},
            "repo_path": {"type": "string", "description": "Ruta del repo a consultar.", "default": "."},
            "task_type": {"type": "string", "description": "auto|code_query|refactor|debug|review|search|code_gen|optimize|audit", "default": "auto"},
            "budget_tokens": {"type": "integer", "description": "Tope de tokens del contexto (0 = automatico segun tarea).", "default": 0},
        },
        "required": ["query"],
    },
)


# --- Tools DETERMINISTAS (grafo): respuesta estructural con prueba, CERO tokens LLM ---
_repo_arg = {"repo_path": {"type": "string", "description": "Ruta del repo/monorepo.", "default": "."}}
_GRAPH_TOOLS = [
    types.Tool(
        name="trace",
        description=("DETERMINISTA, con prueba, sin alucinar. Devuelve el camino de "
            "llamadas de un simbolo a otro (como fluye el control/dato de A a B), "
            "incluso cruzando archivos, repos y lenguajes (frontend->endpoint->DB). "
            "Cada salto citado como archivo:linea. Usalo para 'como llega X a Y'."),
        inputSchema={"type": "object", "properties": {
            "src": {"type": "string", "description": "Simbolo origen."},
            "dst": {"type": "string", "description": "Simbolo destino."}, **_repo_arg},
            "required": ["src", "dst"]}),
    types.Tool(
        name="impact",
        description=("DETERMINISTA, con prueba. Que se ROMPE si cambias un simbolo: "
            "cierre transitivo de todos sus llamadores, cada uno citado archivo:linea. "
            "Cero alucinacion: es el grafo real, no una estimacion del LLM."),
        inputSchema={"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Simbolo a cambiar."}, **_repo_arg},
            "required": ["symbol"]}),
    types.Tool(
        name="who_calls",
        description="DETERMINISTA, con prueba. Quien llama a un simbolo (callers directos), citado archivo:linea.",
        inputSchema={"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Simbolo."}, **_repo_arg},
            "required": ["symbol"]}),
    types.Tool(
        name="where",
        description="DETERMINISTA, con prueba. Donde se define un simbolo, citado archivo:linea (todas las definiciones).",
        inputSchema={"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Simbolo."}, **_repo_arg},
            "required": ["symbol"]}),
    types.Tool(
        name="guard",
        description=("DETERMINISTA, con prueba, cero LLM. ANTES de editar un simbolo: muestra el "
            "RADIO DE EXPLOSION (que se rompe, transitivo, incluso cross-lenguaje via HTTP) y marca "
            "que afectados estan CUBIERTOS por tests y cuales NO (riesgo). Usalo antes de cambiar "
            "codigo para no introducir regresiones que un revisor-LLM se perderia."),
        inputSchema={"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Simbolo que vas a cambiar."}, **_repo_arg},
            "required": ["symbol"]}),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [_TOOL] + _GRAPH_TOOLS


def _relativize(text: str, repo: str) -> str:
    """Citas con ruta relativa al repo: menos tokens y legible para el cliente MCP."""
    pref = repo.replace("\\", "/").rstrip("/") + "/"
    return text.replace("\\", "/").replace(pref, "")


def _run_graph_tool(name: str, args: dict) -> str:
    repo = os.path.abspath(args.get("repo_path") or ".")
    gq = _graphquery(repo)
    if name == "trace":
        out = gq.trace(args["src"], args["dst"]).render()
    elif name == "impact":
        out = gq.impact(args["symbol"]).render()
    elif name == "who_calls":
        out = gq.who_calls(args["symbol"]).render()
    elif name == "where":
        out = gq.where(args["symbol"]).render()
    elif name == "guard":
        # Guardian sobre las MISMAS cápsulas (con boundary ya cosido por _graphquery).
        out = Guardian(_get_indexer().get_capsules()).review(args["symbol"]).render()
    else:
        raise ValueError(f"Tool de grafo desconocida: {name}")
    return _relativize(out, repo)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Tools deterministas de grafo (sin LLM, respuesta con prueba citable).
    if name in ("trace", "impact", "who_calls", "where", "guard"):
        text = await asyncio.to_thread(_run_graph_tool, name, arguments)
        return [types.TextContent(type="text", text=text)]

    if name != "get_context":
        raise ValueError(f"Tool desconocida: {name}")
    query = arguments.get("query")
    if not query:
        raise ValueError("Falta el parametro obligatorio 'query'.")
    repo = os.path.abspath(arguments.get("repo_path") or ".")
    task_type = arguments.get("task_type", "auto")
    budget = int(arguments.get("budget_tokens", 0) or 0)

    # Estructural inmediato + embedding en background → la primera respuesta llega en
    # segundos aunque el repo tenga 60k cápsulas (no bloquea 4 min embebiendo).
    def _work():
        _ensure_structural(repo)
        _embed_bg(repo)  # no bloquea; sube el recall semántico cuando termine
        return compute_context(repo, query, task_type, budget)

    result = await asyncio.to_thread(_work)
    header = (f"[leo-code KC-RAG | task={result['task_type']} | ~{result['tokens']} tok "
              f"| {result['capsules_total']} capsulas indexadas]\n\n")
    return [types.TextContent(type="text", text=_relativize(header + result["context"], repo))]


def _warmup(repo: str):
    """Arranque sin bloquear el handshake MCP. Lo ÚNICO que debe ir en el hilo
    principal es el IMPORT de torch (deadlockea si se importa por primera vez en un
    worker thread en Windows); la carga del modelo (~10s+, o minutos con descarga HF
    fría) va a background — antes bloqueaba el handshake y Claude Code puede matar
    el server por timeout. Las tools de grafo no necesitan encoder; el primer
    get_context que llegue se sincroniza solo.
    """
    try:
        # Solo los IMPORTS (no la carga del modelo): la cadena torch/sentence_transformers
        # debe importarse entera en el hilo principal — dos threads compitiendo por su
        # primer import se deadlockean en el import lock en Windows.
        import torch  # noqa: F401
        import sentence_transformers  # noqa: F401
    except Exception as e:
        print(f"[leo-mcp] import encoder fallo: {e}", file=sys.stderr)

    def _bg():
        try:
            _get_vector_store(repo).search("warmup")  # carga el encoder/modelo
        except Exception as e:
            print(f"[leo-mcp] warmup encoder fallo: {e}", file=sys.stderr)
        _ensure_structural(repo)
        _embed_bg(repo)

    threading.Thread(target=_bg, daemon=True, name="warmup-bg").start()


async def main():
    # El canal MCP usa stdout. Pero el indexer y otras libs imprimen a stdout con
    # print() (en este y otros threads) y eso corromperia el protocolo. Capturamos
    # el stdout REAL para el protocolo y redirigimos sys.stdout a stderr: cualquier
    # print() ruidoso va a stderr y no contamina los mensajes JSON-RPC.
    protocol_stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
    sys.stdout = sys.stderr
    if os.getenv("LEO_DEBUG_DUMP"):  # diagnóstico: volcar stacks periódicamente a stderr
        import faulthandler
        faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
    _warmup(os.path.abspath(os.getenv("LEO_REPO", ".")))
    async with stdio_server(stdout=protocol_stdout) as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run_stdio():
    """Entrypoint síncrono para console_scripts (leo-code-mcp-stdio)."""
    asyncio.run(main())


if __name__ == "__main__":
    run_stdio()
