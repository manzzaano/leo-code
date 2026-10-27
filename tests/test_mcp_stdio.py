"""E2E: el servidor MCP real por stdio, lanzado como lo lanza un cliente (npx → uvx →
`leo-mcp`), con la instalación base (sin extra semántico).

Regresión 2026-09-15: sin torch precargado, el primer import de numpy (BM25) ocurría
en el worker de la 1ª get_context y se colgaba en Windows (extensión C importada por
primera vez en un thread mientras el hilo principal espera en el pipe stdio)."""

import asyncio
import os
import sys
from pathlib import Path


def test_stdio_server_answers_graph_and_first_get_context(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    (tmp_path / "app.py").write_text(
        "def helper():\n    return 1\n\n\ndef main():\n    return helper()\n", encoding="utf-8")
    env = {**os.environ, "LEO_SEMANTIC": "0", "LEO_CACHE_DIR": str(tmp_path / "cache"),
           "LEO_REPO": str(tmp_path), "PYTHONUTF8": "1",
           "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    params = StdioServerParameters(command=sys.executable, args=["-m", "leo_code.cli"],
                                   env=env, cwd=str(tmp_path))

    async def session():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as s:
                init = await s.initialize()
                assert init.server_info.name == "leo-mcp" and init.instructions
                # Las dos tools solo leen: el cliente puede mostrarlo ("read-only").
                for tool in (await s.list_tools()).tools:
                    assert tool.title and tool.annotations.read_only_hint is True
                    assert tool.annotations.destructive_hint is False and tool.annotations.idempotent_hint is True
                g = await s.call_tool("graph", {"op": "who_calls", "symbol": "helper"})
                assert "main" in g.content[0].text
                # Un error de uso llega al agente como resultado legible, no como error de protocolo.
                bad = await s.call_tool("graph", {"op": "nope"})
                assert bad.is_error and "Invalid op" in bad.content[0].text
                c = await asyncio.wait_for(s.call_tool("get_context", {"query": "what does main do"}), 60)
                assert not c.is_error and "helper" in c.content[0].text

    asyncio.run(asyncio.wait_for(session(), 120))


def test_stdout_carries_only_json_rpc_until_exit(tmp_path):
    """Regresión SDK v2: el indexer hace print() durante el warmup; con stdout en un pipe
    quedaba en el buffer de Python y se vaciaba al salir, con el fd 1 ya devuelto al canal."""
    import json
    import subprocess
    (tmp_path / "app.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    env = {**os.environ, "LEO_SEMANTIC": "0", "LEO_CACHE_DIR": str(tmp_path / "cache"),
           "LEO_REPO": str(tmp_path), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "graph", "arguments": {"op": "where", "symbol": "helper"}}}]
    out = subprocess.run([sys.executable, "-m", "leo_code.cli"], env=env, cwd=str(tmp_path),
                         input="".join(json.dumps(m) + "\n" for m in msgs),
                         capture_output=True, text=True, timeout=120).stdout
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines and all(json.loads(ln).get("jsonrpc") == "2.0" for ln in lines), out[:500]
