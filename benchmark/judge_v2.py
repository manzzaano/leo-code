"""Juicio criterio M1 v2: pooled + mediana por tarea sobre N corridas pareadas.

Uso: python benchmark/judge_v2.py results_real/harness_run1.json [run2.json ...]
"""
import json
import statistics
import sys
from pathlib import Path


def load(paths):
    rows = []
    for p in paths:
        rows.extend(json.loads(Path(p).read_text(encoding="utf-8")))
    return rows


def main(paths):
    rows = load(paths)
    oc = [r for r in rows if r["system"].lower() == "oc"]
    mcp = [r for r in rows if r["system"].lower() == "ocmcp"]

    def tot(rs, k):
        return sum(r[k] for r in rs)

    tok_oc, tok_mcp = tot(oc, "tokens"), tot(mcp, "tokens")
    dur_oc, dur_mcp = tot(oc, "duration_ms"), tot(mcp, "duration_ms")
    sc_oc = statistics.mean(r["score_total"] for r in oc)
    sc_mcp = statistics.mean(r["score_total"] for r in mcp)

    # mediana por tarea: delta% de tokens pareado por (task_id, corrida)
    deltas = []
    wins = 0
    by_task = {}
    for a, b in zip(oc, mcp):
        assert a["task_id"] == b["task_id"], "corridas no pareadas"
        if a["tokens"] == 0 or b["tokens"] == 0:  # timeout en cualquiera: par no comparable
            continue
        d = (b["tokens"] - a["tokens"]) / a["tokens"] * 100
        deltas.append(d)
        by_task.setdefault(a["task_id"], []).append(d)
        if d < 0:
            wins += 1

    med = statistics.median(deltas)
    print(f"n corridas: {len(paths)} | pares comparables: {len(deltas)}")
    print(f"tokens  pooled: OC {tok_oc:,} vs OCMCP {tok_mcp:,} -> {100*(tok_mcp-tok_oc)/tok_oc:+.1f}%")
    print(f"tokens  mediana/tarea: {med:+.1f}% | gana OCMCP en {wins}/{len(deltas)} pares")
    print(f"dur     pooled: {100*(dur_mcp-dur_oc)/dur_oc:+.1f}%")
    print(f"score   OC {sc_oc:.2f} vs OCMCP {sc_mcp:.2f} ({sc_mcp-sc_oc:+.2f})")
    n_mcp_calls = sum(sum(r.get("mcp_calls", {}).values()) for r in mcp)
    n_red = sum(r.get("redundant_native_after_ctx", 0) for r in mcp)
    timeouts = [(r["system"], r["task_id"]) for r in rows if r["tokens"] == 0]
    print(f"mcp_calls/tarea: {n_mcp_calls/len(mcp):.1f} | relecturas tras ctx: {n_red} | timeouts: {timeouts or 'ninguno'}")
    print("\npor tarea (mediana de deltas entre corridas):")
    for t in sorted(by_task, key=lambda t: statistics.median(by_task[t])):
        ds = by_task[t]
        print(f"  {t:20s} {statistics.median(ds):+8.1f}%  ({', '.join(f'{d:+.0f}%' for d in ds)})")

    # criterio v2
    tok_ok = abs(med) <= 10
    dur_ok = (dur_mcp - dur_oc) / dur_oc <= 0.10
    sc_ok = sc_mcp >= sc_oc
    print(f"\nCRITERIO v2: tokens ±10% {'OK' if tok_ok else 'FALLA'} | dur <=+10% {'OK' if dur_ok else 'FALLA'} | score >= {'OK' if sc_ok else 'FALLA'}")
    return 0 if (tok_ok and dur_ok and sc_ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
