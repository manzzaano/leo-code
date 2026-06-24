"""Wrapper ligero para ejecutar AgentLoop como subproceso (evita bug de click con runpy).

Uso: python benchmark/leo_runner.py "query" /path/to/repo [model]
"""

import os
import sys
import asyncio
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import io

# Windows: stdout por defecto es cp1252 y crashea al imprimir → / — / emojis que
# el modelo emite. Forzar UTF-8 para no perder respuestas en el benchmark.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code.rag.agent.loop import AgentLoop
from leo_code.rag.agent.tools import ToolRegistry


async def main():
    query = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else "."
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-chat"
    try:
        agent = AgentLoop(tools=ToolRegistry(), max_iterations=15)
        result = await agent.run(query, repo_path=repo, model=model, use_kc_rag=True, session_id=None, history=None)
        resp = result.get("respuesta", "")
        if len(resp) < 100:
            import sys as _sys
            _sys.stderr.write(f"[LEO_RESULT_LEN={len(resp)}] keys={list(result.keys())}\n")
        print(resp)
    except Exception as e:
        print(f"[ERROR: {e}]")


if __name__ == "__main__":
    asyncio.run(main())
