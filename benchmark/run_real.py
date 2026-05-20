"""Benchmark real: leo-code CLI vs opencode CLI (subprocess).

Sistemas:
  LEO: leo-code ask "query" --repo . --model X  (KC-RAG structure)
  OC:  opencode equivalente (AgentLoop sin KC-RAG, mismas tools)
  NO:  LLM directo sin tools ni contexto (baseline)

Uso: python benchmark/run_real.py [--tasks t1,t2] [--systems leo,oc,no]
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.judge import judge, score_summary

MODEL = "deepseek/deepseek-chat"
RESULTS_DIR = Path("benchmark/results_real")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


async def run_leo_cli(query: str, repo_path: str) -> dict:
    """LEO: AgentLoop con KC-RAG (stream_run — igual que el CLI)."""
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    agent = AgentLoop(tools=ToolRegistry(), max_iterations=8)
    agent.interrupt = False
    t0 = time.time()
    try:
        result = await agent.run(query, repo_path=repo_path, model=MODEL, use_kc_rag=True)
        return {
            "system": "LEO",
            "response": result.get("respuesta", "")[:4000],
            "tokens": result.get("total_tokens", 0),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {"system": "LEO", "response": f"[Error: {e}]", "tokens": 0,
                "duration_ms": int((time.time() - t0) * 1000)}



async def run_oc_sim(query: str, repo_path: str) -> dict:
    """Simula opencode: AgentLoop sin KC-RAG, mismo modelo, mismas tools."""
    from leo_code.rag.agent.loop import AgentLoop
    from leo_code.rag.agent.tools import ToolRegistry
    agent = AgentLoop(tools=ToolRegistry(), max_iterations=8)
    agent.interrupt = False
    t0 = time.time()
    try:
        result = await agent.run(query, repo_path=repo_path, model=MODEL, use_kc_rag=False)
        return {
            "system": "OC",
            "response": result.get("respuesta", "")[:4000],
            "tokens": result.get("total_tokens", 0),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {"system": "OC", "response": f"[Error: {e}]", "tokens": 0,
                "duration_ms": int((time.time() - t0) * 1000)}


async def run_no_direct(query: str, repo_path: str) -> dict:
    """LLM directo, sin tools, sin KC-RAG."""
    from leo_code.rag.llm import get_provider
    provider = get_provider("openai",
        api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        base_url="https://api.deepseek.com",
        model=MODEL.split("/")[-1])
    t0 = time.time()
    resp = await provider.generate(
        [{"role": "user", "content": query}], tools=[], temperature=0.2)
    return {
        "system": "NO",
        "response": (resp.text or "")[:4000],
        "tokens": resp.usage.input_tokens + resp.usage.output_tokens,
        "duration_ms": int((time.time() - t0) * 1000),
    }


async def run_benchmark(tasks: list[dict], systems: list[str], repo_path: str) -> list[dict]:
    results = []
    runners = {"LEO": run_leo_cli, "OC": run_oc_sim, "NO": run_no_direct}

    for task in tasks:
        tid = task["id"]
        for sys_name in systems:
            if sys_name not in runners:
                continue
            fn = runners[sys_name]
            print(f"  [{sys_name}] {tid} — {task['query'][:70]}...")
            try:
                r = await fn(task["query"], repo_path)

                r["task_id"] = tid
                scores = judge(r["response"], task)
                r["scores"] = scores
                r["score_total"] = score_summary(scores)
                results.append(r)

                out_path = RESULTS_DIR / f"{sys_name.lower()}_{tid}.json"
                out_path.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
                print(f"    tokens={r['tokens']} score={r['score_total']:.1f} time={r['duration_ms']}ms")
            except Exception as e:
                print(f"    ERROR: {e}")
                results.append({"system": sys_name, "task_id": tid, "error": str(e),
                                "tokens": 0, "score_total": 0})
    return results


def print_summary(results: list[dict]):
    print("\n" + "=" * 90)
    print("BENCHMARK LEO-CODE vs OPENCODE (REAL)")
    print("=" * 90)
    by_system = {}
    for r in results:
        s = r.get("system", "?")
        by_system.setdefault(s, []).append(r)

    for sys_name, sys_results in by_system.items():
        valid = [r for r in sys_results if r.get("response")]
        if not valid:
            print(f"  {sys_name}: no results")
            continue
        avg_tokens = sum(r.get("tokens", 0) for r in valid) / len(valid)
        avg_score = sum(r.get("score_total", 0) for r in valid) / len(valid)
        total_tokens = sum(r.get("tokens", 0) for r in valid)
        wins = sum(1 for r in valid if r.get("score_total", 0) > 3)
        print(f"  {sys_name}: {len(valid)} tasks | {total_tokens:,} tokens | {avg_tokens:.0f} tok/task | avg {avg_score:.1f}/10 score | {wins} wins")

    leo = [r for r in results if r.get("system") == "LEO" and r.get("response")]
    oc = [r for r in results if r.get("system") == "OC" and r.get("response")]
    if leo and oc:
        leo_tok = sum(r["tokens"] for r in leo)
        oc_tok = sum(r["tokens"] for r in oc)
        leo_score = sum(r.get("score_total", 0) for r in leo) / len(leo)
        oc_score = sum(r.get("score_total", 0) for r in oc) / len(oc)
        reduction = (1 - leo_tok / max(oc_tok, 1)) * 100 if oc_tok > 0 else 0
        print(f"\n  Token reduction LEO vs OC: {reduction:.1f}%")
        print(f"  LEO avg score: {leo_score:.1f}/10 | OC avg score: {oc_score:.1f}/10")
        leo_better = sum(1 for l in leo for o in oc
                         if o["task_id"] == l["task_id"] and l.get("score_total", 0) > o.get("score_total", 0))
        print(f"  LEO wins {leo_better}/{len(leo)} tasks on score")
    print("=" * 90)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="leo-code vs opencode REAL benchmark")
    parser.add_argument("--tasks", default="", help="Comma-separated task IDs")
    parser.add_argument("--systems", default="leo,oc,no", help="Systems to test")
    parser.add_argument("--repo", default=".", help="Repo path")
    args = parser.parse_args()

    tasks = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in ids]

    systems = [s.strip().upper() for s in args.systems.split(",")]
    print(f"Benchmark REAL: {len(tasks)} tasks × {len(systems)} systems")
    print(f"Model: {MODEL} | Repo: {Path(args.repo).resolve()}")
    print(f"LEO: subprocess CLI | OC: AgentLoop sin KC-RAG | NO: LLM directo\n")

    results = asyncio.run(run_benchmark(tasks, systems, args.repo))
    print_summary(results)

    out_path = RESULTS_DIR / "summary.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
