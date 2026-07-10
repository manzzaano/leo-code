"""Wrapper ligero para ejecutar AgentLoop.rag_direct() como subproceso (mismo patron
que leo_runner.py, pero UNA llamada sin tools en vez del loop completo).

Uso: python benchmark/leo_rag_runner.py "query" /path/to/repo [model]
"""

import sys
import asyncio
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.bench_qdrant import setup_qdrant_path
setup_qdrant_path()

from leo_code.rag.agent.loop import AgentLoop
from leo_code.rag.agent.tools import ToolRegistry


async def main():
    query = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else "."
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-chat"
    try:
        agent = AgentLoop(tools=ToolRegistry())
        result = await agent.rag_direct(query, repo_path=repo, model=model, session_id=None)
        resp = result.get("respuesta", "")
        sys.stderr.write(f"[LEO_TOKENS={result.get('total_tokens', 0)}]\n")
        print(resp)
    except Exception as e:
        print(f"[ERROR: {e}]")


if __name__ == "__main__":
    asyncio.run(main())
