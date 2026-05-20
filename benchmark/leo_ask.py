"""Launcher para benchmark: emula leo-code ask como subproceso."""
import sys, asyncio, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from leo_code.rag.agent.loop import AgentLoop
from leo_code.rag.agent.tools import ToolRegistry

async def main():
    query = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else "."
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-chat"
    try:
        agent = AgentLoop(tools=ToolRegistry(), max_iterations=15)
        result = await agent.run(query, repo_path=repo, model=model, use_kc_rag=True)
        # Write response to stderr to avoid indexer noise on stdout
        resp = json.dumps({"response": result.get("respuesta", ""),
                           "tokens": result.get("total_tokens", 0),
                           "iterations": result.get("iterations", 0),
                           "duration_ms": result.get("duration_ms", 0)},
                          ensure_ascii=False)
        sys.stderr.write(f"__LEO_RESULT__{resp}\n")
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"__LEO_RESULT__{json.dumps({'response': f'ERROR: {e}', 'tokens': 0, 'iterations': 0, 'duration_ms': 0}, ensure_ascii=False)}\n")
        sys.stderr.flush()

asyncio.run(main())
