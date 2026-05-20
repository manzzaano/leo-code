"""Benchmark real: leo-code vs opencode CLI (subprocesos paralelos, judge separado).

Uso: python benchmark/run_real.py [--tasks t1,t2] [--systems leo,oc,no] [--batch 3]
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.judge import judge, score_summary

MODEL = "deepseek/deepseek-v4-pro"
RUNNER = str(Path(__file__).parent / "leo_runner.py")
RESULTS_DIR = Path("benchmark/results_real")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BATCH_SIZE = 3


def run_leo_subprocess(query: str, repo_path: str) -> dict:
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        r = subprocess.run(
            [sys.executable, RUNNER, query, repo_path, MODEL],
            capture_output=True, text=True, timeout=180, env=env,
        )
        response = (r.stdout or "").strip() or (r.stderr or "").strip()
        return {"system": "LEO", "response": response[:4000], "tokens": len(response) // 4,
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "LEO", "response": "[Timeout]", "tokens": 0, "duration_ms": 180000}
    except Exception as e:
        return {"system": "LEO", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


def run_oc_subprocess(query: str, repo_path: str) -> dict:
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        r = subprocess.run(
            ["opencode", "run", query, "-m", "deepseek/deepseek-v4-pro"],
            capture_output=True, text=True, timeout=180, cwd=repo_path, env=env,
        )
        lines = []
        for line in (r.stdout + "\n" + (r.stderr or "")).split("\n"):
            s = line.strip()
            if not s or s[:4] in ("INFO", "WARN", "ERRO", "   ") or s[0] in "┌│└●":
                continue
            lines.append(s)
        response = "\n".join(lines).strip()
        return {"system": "OC", "response": response[:4000], "tokens": len(response) // 4,
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"system": "OC", "response": "[Timeout]", "tokens": 0, "duration_ms": 180000}
    except FileNotFoundError:
        return {"system": "OC", "response": "[opencode not installed]", "tokens": 0, "duration_ms": 0}
    except Exception as e:
        return {"system": "OC", "response": f"[Error: {e}]", "tokens": 0, "duration_ms": 0}


def run_no_direct(query: str) -> dict:
    import asyncio as _asyncio
    async def _run():
        from leo_code.rag.llm import get_provider
        provider = get_provider("openai",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com", model="deepseek-chat")
        t0 = time.time()
        resp = await provider.generate([{"role": "user", "content": query}], tools=[], temperature=0.2)
        return {"system": "NO", "response": (resp.text or "")[:4000],
                "tokens": resp.usage.input_tokens + resp.usage.output_tokens,
                "duration_ms": int((time.time() - t0) * 1000)}
    return _asyncio.run(_run())


async def run_batch(tasks: list[dict], repo_path: str, systems: list[str]) -> list[dict]:
    """Ejecuta en paralelo, SIN judge."""
    async def run_one(task, sys_name):
        tid = task["id"]
        print(f"    [{sys_name}] {tid} ...")
        try:
            if sys_name == "LEO":
                r = await asyncio.to_thread(run_leo_subprocess, task["query"], repo_path)
            elif sys_name == "OC":
                r = await asyncio.to_thread(run_oc_subprocess, task["query"], repo_path)
            else:
                r = run_no_direct(task["query"])
            r["task_id"] = tid
            print(f"      tok={r.get('tokens',0)} time={r.get('duration_ms',0)}ms")
            return r
        except Exception as e:
            print(f"      ERR: {e}")
            return {"system": sys_name, "task_id": tid, "response": f"[{e}]", "tokens": 0, "duration_ms": 0}

    coros = [run_one(task, s) for task in tasks for s in systems if s in ("LEO", "OC", "NO")]
    return await asyncio.gather(*coros)


def judge_results(raw_results: list[dict], tasks: list[dict]) -> list[dict]:
    """Judge secuencial después de ejecutar."""
    task_map = {t["id"]: t for t in tasks}
    for r in raw_results:
        tid = r.get("task_id", "")
        task = task_map.get(tid)
        if task and r.get("response") and r["response"][:1] != "[":
            scores = judge(r["response"], task)
            r["scores"] = scores
            r["score_total"] = score_summary(scores)
        else:
            r["scores"] = {"relevancia": 1, "correccion": 1, "completitud": 1, "accionabilidad": 1}
            r["score_total"] = 1.0
        print(f"    Judge [{r['system']}] {tid}: {r['score_total']:.1f}/10")
    return raw_results


def print_summary(results: list[dict]):
    print("\n" + "=" * 80)
    print("LEO-CODE vs OPENCODE - BENCHMARK REAL")
    print(f"Model: {MODEL}")
    print("=" * 80)
    by_sys = {}
    for r in results:
        by_sys.setdefault(r["system"], []).append(r)
    for s in ["LEO", "OC", "NO"]:
        valid = [r for r in by_sys.get(s, []) if r.get("response")]
        if not valid:
            continue
        tok = sum(r.get("tokens", 0) for r in valid)
        score = sum(r.get("score_total", 0) for r in valid) / len(valid)
        time_ms = sum(r.get("duration_ms", 0) for r in valid) / len(valid)
        print(f"  {s}: {len(valid)} tasks | {tok:,} tok | {tok/len(valid):.0f} tok/task | {score:.1f}/10 | {time_ms:.0f}ms avg")
    leo = [r for r in results if r["system"] == "LEO" and r.get("response")]
    oc = [r for r in results if r["system"] == "OC" and r.get("response")]
    if leo and oc:
        lt = sum(r["tokens"] for r in leo)
        ot = sum(r["tokens"] for r in oc)
        ls = sum(r.get("score_total", 0) for r in leo) / len(leo)
        os = sum(r.get("score_total", 0) for r in oc) / len(oc)
        print(f"\n  Token reduction: {(1 - lt/max(ot,1))*100:.1f}%")
        print(f"  LEO: {ls:.1f}/10 | OC: {os:.1f}/10")
        faster = sum(r.get("duration_ms", 0) for r in oc) / max(sum(r.get("duration_ms", 0) for r in leo), 1)
        print(f"  LEO is {faster:.1f}x faster")
    print("=" * 80)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", default="")
    p.add_argument("--systems", default="leo,oc,no")
    p.add_argument("--repo", default=".")
    p.add_argument("--batch", type=int, default=BATCH_SIZE)
    args = p.parse_args()

    tasks = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in ids]
    systems = [s.strip().upper() for s in args.systems.split(",")]
    batches = [tasks[i:i + args.batch] for i in range(0, len(tasks), args.batch)]

    print(f"Benchmark: {len(tasks)} tasks x {len(systems)} systems")
    print(f"Model: {MODEL} | Batches: {len(batches)} x {args.batch}\n")

    t0 = time.time()
    all_results = []
    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} - running...")
        raw = asyncio.run(run_batch(batch, args.repo, systems))
        all_results.extend(raw)

    print(f"\n  Judging...")
    all_results = judge_results(all_results, tasks)

    total = int(time.time() - t0)
    print(f"\n  Total: {total}s")
    print_summary(all_results)

    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
