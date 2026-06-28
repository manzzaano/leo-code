"""Prueba la mitad 'vía MCP' del objetivo con un cliente MCP REAL.

Arranca leo_code.server.mcp_server por stdio (igual que haría Claude Code/opencode),
hace el handshake MCP (initialize -> tools/list -> tools/call) y mide, por símbolo:
tokens del contexto que el agente recibe vía MCP vs tokens del archivo entero que
leería sin leo. Cero LLM, cero API key — mide la ENTREGA del contexto, que es lo
que determina el ahorro de tokens del agente.

Uso:  python benchmark/mcp_client_bench.py
Sale !=0 si recall < 100% o reducción media < umbral.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code.core.tokens import count_tokens

UMBRAL_RED = 0.70  # vs 1 archivo (conservador); vs multi-archivo es bastante mayor

CASES = [
    ("detect_frameworks", "leo_code/core/parser.py"),
    ("compress",          "leo_code/rag/compressor.py"),
    ("stream_run",        "leo_code/rag/agent/loop.py"),
    ("get_context",       "leo_code/server/server.py"),
    ("_plan",             "leo_code/rag/agent/goal.py"),
    ("_find_block_end",   "leo_code/core/parser_generic.py"),
]


async def run() -> tuple[float, int, int]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = str(Path(".").resolve())
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1"}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "leo_code.server.mcp_server"], env=env,
    )

    reds, recall = [], 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"MCP handshake OK | tools expuestas: {names}\n")
            assert "get_context" in names, "el servidor MCP no expone get_context"

            print(f"{'symbol':<18}{'file_tok':>9}{'mcp_tok':>9}{'reduc':>7}  sym?")
            print("-" * 54)
            for sym, f in CASES:
                res = await session.call_tool(
                    "get_context",
                    {"query": f"¿Qué hace {sym} en {f}?", "repo_path": repo},
                )
                ctx = res.content[0].text if res.content else ""
                mcp_tok = count_tokens(ctx)
                file_tok = count_tokens(Path(f).read_text(encoding="utf-8", errors="replace"))
                red = 1 - mcp_tok / file_tok if file_tok else 0.0
                present = sym in ctx
                recall += present
                reds.append(red)
                print(f"{sym:<18}{file_tok:>9,}{mcp_tok:>9,}{red:>6.0%}  {'Y' if present else 'N'}")

    avg = sum(reds) / len(reds) if reds else 0.0
    print("-" * 54)
    print(f"\nReducción media vía MCP (vs 1 archivo): {avg:.1%}  (umbral {UMBRAL_RED:.0%})")
    print(f"Recall símbolo: {recall}/{len(CASES)}")
    return avg, recall, len(CASES)


if __name__ == "__main__":
    avg, recall, total = asyncio.run(run())
    ok = avg >= UMBRAL_RED and recall == total
    print("GATE PASS" if ok else "GATE FAIL")
    sys.exit(0 if ok else 1)
