"""Wrapper ligero para ejecutar AgentLoop.rag_direct() como subproceso (mismo patron
que leo_runner.py, pero UNA llamada sin tools en vez del loop completo).

Uso: python benchmark/leo_rag_runner.py "query" /path/to/repo [model]
"""

import os
import sys
import asyncio
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Storage Qdrant propio y efimero por subproceso: el lock de qdrant-local es a nivel
# de DIRECTORIO (no de coleccion) — sin esto, corridas paralelas del benchmark
# (--batch N) se pisan y degradan a indice en memoria. Ver vector_store.py.
import tempfile
os.environ["LEO_QDRANT_PATH"] = tempfile.mkdtemp(prefix="leo_qdrant_bench_")

sys.path.insert(0, str(Path(__file__).parent.parent))

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
