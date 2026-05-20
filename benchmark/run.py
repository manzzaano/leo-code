"""Benchmark runner — ejecuta 15 tareas en 3 sistemas y compara.

Sistemas:
  LEO: leo-code con KC-RAG (AgentLoop.stream_run con contexto)
  OC:  agente sin KC-RAG (mismas tools, sin contexto RAG)
  NO:  LLM directo sin tools ni contexto (baseline mínimo)

Requiere: DEEPSEEK_API_KEY o OPENAI_API_KEY en el entorno.

Uso: python benchmark/run.py [--tasks t1,t2,t3] [--systems leo,oc,no]
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.judge import judge, score_summary

MODEL = "deepseek/deepseek-chat"  # non-thinking for reliable streaming + tools
RESULTS_DIR = Path("benchmark/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_task_leo(task: dict, repo_path: str) -> dict:
    """Ejecuta tarea con leo-code (KC-RAG activo)."""
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    agent = AgentLoop(tools=ToolRegistry(), max_iterations=8)
    agent.interrupt = False
    t0 = time.time()
    try:
        result = await agent.run(task["query"], repo_path=repo_path, model=MODEL, use_kc_rag=True)
        return {
            "system": "LEO",
            "task_id": task["id"],
            "response": result.get("respuesta", ""),
            "tokens": result.get("total_tokens", 0),
            "iterations": result.get("iterations", 0),
            "duration_ms": int((time.time() - t0) * 1000),
            "finish": result.get("finish", "stop"),
        }
    except Exception as e:
        return {"system": "LEO", "task_id": task["id"], "response": f"ERROR: {e}", "tokens": 0,
                "iterations": 0, "duration_ms": int((time.time() - t0) * 1000), "finish": "error"}


async def run_task_oc(task: dict, repo_path: str) -> dict:
    """Ejecuta tarea sin KC-RAG (agente con tools pero sin contexto RAG)."""
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    agent = AgentLoop(tools=ToolRegistry(), max_iterations=8)
    agent.interrupt = False
    t0 = time.time()
    try:
        result = await agent.run(task["query"], repo_path=repo_path, model=MODEL, use_kc_rag=False)
        return {
            "system": "OC",
            "task_id": task["id"],
            "response": result.get("respuesta", ""),
            "tokens": result.get("total_tokens", 0),
            "iterations": result.get("iterations", 0),
            "duration_ms": int((time.time() - t0) * 1000),
            "finish": result.get("finish", "stop"),
        }
    except Exception as e:
        return {"system": "OC", "task_id": task["id"], "response": f"ERROR: {e}", "tokens": 0,
                "iterations": 0, "duration_ms": int((time.time() - t0) * 1000), "finish": "error"}


async def run_task_oc(task: dict, repo_path: str) -> dict:
    """Ejecuta tarea sin KC-RAG (agente con tools pero sin contexto RAG)."""
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    agent = AgentLoop(tools=ToolRegistry(), max_iterations=10)
    t0 = time.time()
    result = await agent.run(task["query"], repo_path=repo_path, model=MODEL, use_kc_rag=False)
    return {
        "system": "OC",
        "task_id": task["id"],
        "query": task["query"],
        "response": result.get("respuesta", ""),
        "tokens": result.get("total_tokens", 0),
        "iterations": result.get("iterations", 0),
        "duration_ms": int((time.time() - t0) * 1000),
        "finish": result.get("finish", "stop"),
    }


async def run_task_no(task: dict, repo_path: str) -> dict:
    """Ejecuta tarea con LLM directo (sin tools, sin KC-RAG)."""
    from leo_code.rag.llm import get_provider
    provider = get_provider("openai",
        api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        base_url="https://api.deepseek.com",
        model=MODEL.split("/")[-1])
    t0 = time.time()
    resp = await provider.generate(
        [{"role": "user", "content": task["query"]}],
        tools=[], temperature=0.2,
    )
    return {
        "system": "NO",
        "task_id": task["id"],
        "query": task["query"],
        "response": resp.text or "",
        "tokens": resp.usage.input_tokens + resp.usage.output_tokens,
        "iterations": 1,
        "duration_ms": int((time.time() - t0) * 1000),
        "finish": "stop",
    }


async def run_benchmark(tasks: list[dict], systems: list[str], repo_path: str) -> list[dict]:
    """Ejecuta todas las tareas en todos los sistemas."""
    results = []
    runners = {"LEO": run_task_leo, "OC": run_task_oc, "NO": run_task_no}

    for task in tasks:
        tid = task["id"]
        for sys_name in systems:
            if sys_name not in runners:
                continue
            print(f"  [{sys_name}] {tid} — {task['query'][:80]}...")
            try:
                r = await runners[sys_name](task, repo_path)
                scores = judge(r["response"], task)
                r["scores"] = scores
                r["score_total"] = score_summary(scores)
                results.append(r)
                # Save individual result
                (RESULTS_DIR / f"{sys_name.lower()}_{tid}.json").write_text(
                    json.dumps(r, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
                print(f"    tokens={r['tokens']} score={r['score_total']}")
            except Exception as e:
                print(f"    ERROR: {e}")
                results.append({"system": sys_name, "task_id": tid, "error": str(e)})
    return results


def print_summary(results: list[dict]):
    """Imprime tabla resumen en consola."""
    print("\n" + "=" * 90)
    print("BENCHMARK RESULTS")
    print("=" * 90)

    by_system = {}
    for r in results:
        s = r.get("system", "?")
        by_system.setdefault(s, []).append(r)

    for sys_name, sys_results in by_system.items():
        valid = [r for r in sys_results if r.get("response")]
        if not valid:
            continue
        avg_tokens = sum(r["tokens"] for r in valid) / len(valid)
        avg_score = sum(r.get("score_total", 0) for r in valid) / len(valid)
        total_tokens = sum(r["tokens"] for r in valid)
        print(f"  {sys_name}: {len(valid)} tasks | {total_tokens:,} tokens | avg {avg_score:.1f}/10 score | {avg_tokens:.0f} tok/task")

    # Comparison
    leo = [r for r in results if r.get("system") == "LEO" and r.get("response")]
    oc = [r for r in results if r.get("system") == "OC" and r.get("response")]
    if leo and oc:
        leo_tok = sum(r["tokens"] for r in leo)
        oc_tok = sum(r["tokens"] for r in oc)
        reduction = (1 - leo_tok / max(oc_tok, 1)) * 100
        leo_score = sum(r.get("score_total", 0) for r in leo) / len(leo)
        oc_score = sum(r.get("score_total", 0) for r in oc) / len(oc)
        print(f"\n  Token reduction: {reduction:.1f}%")
        print(f"  LEO score: {leo_score:.1f}/10 | OC score: {oc_score:.1f}/10")
    print("=" * 90)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="leo-code benchmark")
    parser.add_argument("--tasks", default="", help="Comma-separated task IDs (default: all)")
    parser.add_argument("--systems", default="leo,oc,no", help="Systems to test (leo,oc,no)")
    parser.add_argument("--repo", default=".", help="Repo path")
    parser.add_argument("--judge-only", action="store_true", help="Only judge existing results")
    args = parser.parse_args()

    tasks = json.loads(Path("benchmark/tasks.json").read_text())
    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in ids]

    systems = [s.strip().upper() for s in args.systems.split(",")]

    if args.judge_only:
        results = []
        for sys_name in systems:
            for task in tasks:
                path = RESULTS_DIR / f"{sys_name.lower()}_{task['id']}.json"
                if path.exists():
                    r = json.loads(path.read_text())
                    if not r.get("scores"):
                        scores = judge(r.get("response", ""), task)
                        r["scores"] = scores
                        r["score_total"] = score_summary(scores)
                        path.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str))
                    results.append(r)
        print_summary(results)
        return

    print(f"Benchmark: {len(tasks)} tasks × {len(systems)} systems")
    print(f"Model: {MODEL}")
    print(f"Repo: {Path(args.repo).resolve()}")
    print()

    results = asyncio.run(run_benchmark(tasks, systems, args.repo))
    print_summary(results)

    # Save full results
    (RESULTS_DIR / "full_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")


if __name__ == "__main__":
    main()
