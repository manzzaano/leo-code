"""Benchmark JUSTO: leo-code ask vs opencode run (real CLIs via subprocesos).

Mide: tiempo total, calidad de respuesta (LLM Judge).
Uso: python benchmark/run_justo.py [--tasks t1,t2] [--batch 2]
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

MODEL = "deepseek/deepseek-chat"
LEO_CMD = [sys.executable, str(Path(__file__).parent / "leo_ask.py")]
OC_CMD = [r"C:\Users\Ismael\AppData\Roaming\npm\opencode.cmd", "run"]
RESULTS_DIR = Path("benchmark/results_justo")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
BATCH = 2


def run_leo(query: str, repo: str) -> dict:
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        r = subprocess.run(
            LEO_CMD + [query, repo, MODEL],
            capture_output=True, text=True, timeout=300, env=env, cwd=repo,
        )
        # Parse from stderr (leo_ask writes result to stderr)
        stderr = r.stderr or ""
        resp = ""
        tokens = 0
        for line in stderr.split("\n"):
            if line.startswith("__LEO_RESULT__"):
                try:
                    data = json.loads(line.replace("__LEO_RESULT__", ""))
                    resp = data.get("response", "")
                    tokens = data.get("tokens", len(resp) // 4)
                except json.JSONDecodeError:
                    resp = line.replace("__LEO_RESULT__", "")
        if not resp:
            resp = (r.stdout or "").strip()
        return {"system": "LEO", "response": resp[:4000], "tokens": tokens,
                "duration_s": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"system": "LEO", "response": "[TIMEOUT 300s]", "tokens": 0, "duration_s": 300}
    except Exception as e:
        return {"system": "LEO", "response": f"[ERROR: {e}]", "tokens": 0, "duration_s": 0}


def run_oc(query: str, repo: str) -> dict:
    t0 = time.time()
    try:
        env = {**os.environ, "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", "")}
        r = subprocess.run(
            OC_CMD + [query, "-m", "deepseek/deepseek-chat"],
            capture_output=True, text=True, timeout=300, env=env, cwd=repo,
        )
        out = r.stdout or ""
        # Filter ANSI and log lines
        import re as _re
        out = _re.sub(r'\x1b\[[0-9;]*m', '', out)
        lines = []
        for l in out.split("\n"):
            s = l.strip()
            if s and not s[:4] in ("INFO", "WARN", "ERRO") and not s.startswith("---"):
                lines.append(s)
        response = "\n".join(lines).strip()
        return {"system": "OC", "response": response[:4000],
                "duration_s": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"system": "OC", "response": "[TIMEOUT 300s]", "duration_s": 300}
    except Exception as e:
        return {"system": "OC", "response": f"[ERROR: {e}]", "duration_s": 0}


async def run_batch(tasks: list[dict], repo: str, systems: list[str]) -> list[dict]:
    results = []

    async def run_one(task, sys_name):
        tid = task["id"]
        print(f"    [{sys_name}] {tid} ...")
        try:
            if sys_name == "LEO":
                r = await asyncio.to_thread(run_leo, task["query"], repo)
            else:
                r = await asyncio.to_thread(run_oc, task["query"], repo)
            r["task_id"] = tid
            print(f"      {r['duration_s']}s | {len(r.get('response',''))} chars")
            return r
        except Exception as e:
            print(f"      ERR: {e}")
            return {"system": sys_name, "task_id": tid, "response": f"[{e}]", "duration_s": 0}

    coros = [run_one(task, s) for task in tasks for s in systems if s in ("LEO", "OC")]
    batch_results = await asyncio.gather(*coros)
    for r in batch_results:
        if r:
            results.append(r)
    return results


def judge_results(raw: list[dict], tasks: list[dict]) -> list[dict]:
    task_map = {t["id"]: t for t in tasks}
    for r in raw:
        tid = r.get("task_id", "")
        task = task_map.get(tid)
        resp = r.get("response", "")
        if task and resp and resp[:1] != "[" and resp[:1] != "T":
            scores = judge(resp, task)
            r["scores"] = scores
            r["score"] = score_summary(scores)
        else:
            r["scores"] = {}
            r["score"] = 0
        print(f"    Judge [{r['system']}] {tid}: {r['score']:.1f}/10")
    return raw


def print_report(results: list[dict], tasks: list[dict]):
    print("\n" + "=" * 70)
    print("LEO-CODE vs OPENCODE — BENCHMARK REAL")
    print(f"Model: {MODEL}")
    print("=" * 70)

    leo = [r for r in results if r["system"] == "LEO" and r.get("response")]
    oc = [r for r in results if r["system"] == "OC" and r.get("response")]

    print(f"\n{'Tarea':<20} {'LEO time':>8} {'OC time':>8} {'LEO score':>10} {'OC score':>10} {'Winner':>8}")
    print("-" * 70)
    for t in tasks:
        tid = t["id"]
        l = next((r for r in leo if r.get("task_id") == tid), None)
        o = next((r for r in oc if r.get("task_id") == tid), None)
        lt = f"{l['duration_s']:.1f}s" if l else "-"
        ot = f"{o['duration_s']:.1f}s" if o else "-"
        ls = f"{l['score']:.1f}" if l and l.get("score") else "-"
        os = f"{o['score']:.1f}" if o and o.get("score") else "-"
        w = "LEO" if (l and o and l.get("score", 0) > o.get("score", 0)) else ("OC" if (l and o and o.get("score", 0) > l.get("score", 0)) else "-")
        print(f"{tid:<20} {lt:>8} {ot:>8} {ls:>10} {os:>10} {w:>8}")

    if leo and oc:
        avg_leo = sum(r["duration_s"] for r in leo) / len(leo)
        avg_oc = sum(r["duration_s"] for r in oc) / len(oc)
        leo_score = sum(r.get("score", 0) for r in leo) / len(leo)
        oc_score = sum(r.get("score", 0) for r in oc) / len(oc)
        leo_wins = sum(1 for l in leo for o in oc if o.get("task_id") == l.get("task_id") and l.get("score", 0) > o.get("score", 0))
        print(f"\n  Avg time: LEO {avg_leo:.1f}s | OC {avg_oc:.1f}s")
        print(f"  LEO is {avg_oc/avg_leo:.1f}x faster" if avg_leo > 0 else "")
        print(f"  Avg score: LEO {leo_score:.1f}/10 | OC {oc_score:.1f}/10")
        print(f"  LEO wins {leo_wins}/{len(leo)} tasks on score")
    print("=" * 70)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", default="")
    p.add_argument("--batch", type=int, default=BATCH)
    p.add_argument("--repo", default=".")
    args = p.parse_args()

    all_tasks = json.loads(Path("benchmark/tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        ids = set(args.tasks.split(","))
        tasks = [t for t in all_tasks if t["id"] in ids]
    else:
        tasks = all_tasks

    batches = [tasks[i:i + args.batch] for i in range(0, len(tasks), args.batch)]

    print(f"JUSTO Benchmark: {len(tasks)} tasks x 2 systems (LEO + OC)")
    print(f"Model: {MODEL} | Batch: {args.batch} | Batches: {len(batches)}")
    print(f"LEO: python benchmark/leo_ask.py | OC: opencode.cmd run\n")

    t0 = time.time()
    all_results = []
    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} ({len(batch)} tasks) ...")
        batch_results = asyncio.run(run_batch(batch, args.repo, ["LEO", "OC"]))
        all_results.extend(batch_results)

    print(f"\n  Judging {len(all_results)} responses...")
    all_results = judge_results(all_results, tasks)

    elapsed = int(time.time() - t0)
    print(f"\n  Total: {elapsed}s")
    print_report(all_results, tasks)

    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
