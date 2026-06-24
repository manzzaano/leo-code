"""Comparativa 3-vías: LEO actual vs versión anterior vs opencode.

Lee resultados de run_real.py (lista de dicts con task_id/system/score_total/tokens/duration_ms).

Uso:
  python benchmark/compare_3way.py \
    --current benchmark/results_real/summary_current.json \
    --prev    benchmark/results_real/summary_prev.json \
    --oc-from current
"""

import argparse
import json
import statistics
from pathlib import Path


def load(path: str) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def by_task(rows: list[dict], system: str) -> dict[str, dict]:
    return {r["task_id"]: r for r in rows if r.get("system") == system}


def _avg(vals: list[float]) -> float:
    return round(statistics.mean(vals), 2) if vals else 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--current", default="benchmark/results_real/summary_current.json")
    p.add_argument("--prev", default="benchmark/results_real/summary_prev.json")
    p.add_argument("--oc-from", default="current", choices=["current", "prev"],
                   help="de qué run tomar los datos de opencode (OC)")
    args = p.parse_args()

    cur = load(args.current)
    prev = load(args.prev)
    oc_src = cur if args.oc_from == "current" else prev

    leo_cur = by_task(cur, "LEO")
    leo_prev = by_task(prev, "LEO")
    oc = by_task(oc_src, "OC")

    task_ids = sorted(set(leo_cur) | set(leo_prev) | set(oc))

    print("=" * 92)
    print("COMPARATIVA: LEO actual  vs  LEO anterior  vs  opencode   (score/10 · tokens · ms)")
    print("=" * 92)
    hdr = f"{'task':<20} {'LEO-actual':>16} {'LEO-anterior':>16} {'opencode':>16}"
    print(hdr)
    print("-" * 92)

    def cell(r: dict | None) -> str:
        if not r:
            return f"{'—':>16}"
        return f"{r.get('score_total', 0):>5}/{r.get('tokens', 0):>5}t/{r.get('duration_ms', 0)//1000:>3}s"

    agg = {"cur": [], "prev": [], "oc": []}
    tok = {"cur": [], "prev": [], "oc": []}
    for tid in task_ids:
        rc, rp, ro = leo_cur.get(tid), leo_prev.get(tid), oc.get(tid)
        print(f"{tid:<20} {cell(rc)} {cell(rp)} {cell(ro)}")
        if rc: agg["cur"].append(rc["score_total"]); tok["cur"].append(rc["tokens"])
        if rp: agg["prev"].append(rp["score_total"]); tok["prev"].append(rp["tokens"])
        if ro: agg["oc"].append(ro["score_total"]); tok["oc"].append(ro["tokens"])

    print("-" * 92)
    print(f"{'SCORE medio':<20} {_avg(agg['cur']):>16} {_avg(agg['prev']):>16} {_avg(agg['oc']):>16}")
    print(f"{'TOKENS medio':<20} {_avg(tok['cur']):>16} {_avg(tok['prev']):>16} {_avg(tok['oc']):>16}")
    print("=" * 92)

    if agg["cur"] and agg["prev"]:
        d = _avg(agg["cur"]) - _avg(agg["prev"])
        print(f"Δ score  actual vs anterior: {d:+.2f}")
    if agg["cur"] and agg["oc"]:
        d = _avg(agg["cur"]) - _avg(agg["oc"])
        print(f"Δ score  actual vs opencode: {d:+.2f}")


if __name__ == "__main__":
    main()
