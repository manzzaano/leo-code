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
                assert init.serverInfo.name == "leo-mcp" and init.instructions
                g = await s.call_tool("graph", {"op": "who_calls", "symbol": "helper"})
                assert "main" in g.content[0].text
                c = await asyncio.wait_for(s.call_tool("get_context", {"query": "what does main do"}), 60)
                assert not c.isError and "helper" in c.content[0].text

    asyncio.run(asyncio.wait_for(session(), 120))
