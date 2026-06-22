"""Promediado multi-run del benchmark e2e — combate la varianza del juez LLM.

Corre run_real.py N veces y agrega: media ± desviación por tarea y global. Un solo
run no es fiable (±2-3/tarea de ruido); 3+ runs dan número con barras de error.

Uso:  python benchmark/run_avg.py --runs 3 --systems leo --batch 5 [--repo DIR] [--tasks ...]
Los flags que no sean --runs se pasan tal cual a run_real.py.
"""

import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SUMMARY = ROOT / "benchmark" / "results_real" / "summary.json"


def main():
    argv = sys.argv[1:]
    runs = 3
    if "--runs" in argv:
        i = argv.index("--runs")
        runs = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]  # quitar --runs N del passthrough

    snapshots = []
    for n in range(1, runs + 1):
        print(f"\n===== RUN {n}/{runs} =====", flush=True)
        r = subprocess.run([sys.executable, str(ROOT / "benchmark" / "run_real.py"), *argv], cwd=str(ROOT))
        if r.returncode != 0 or not SUMMARY.exists():
            print(f"[run_avg] run {n} falló (exit {r.returncode})")
            continue
        data = json.loads(SUMMARY.read_text(encoding="utf-8"))
        snapshots.append({d["task_id"]: d["score_total"] for d in data})

    if not snapshots:
        print("[run_avg] sin resultados")
        sys.exit(1)

    tasks = sorted(snapshots[0])
    print(f"\n{'task':<22} " + " ".join(f"r{i+1}" for i in range(len(snapshots))) + "   mean  std")
    print("-" * (24 + 5 * len(snapshots) + 12))
    for t in tasks:
        vals = [s.get(t, 0.0) for s in snapshots]
        print(f"{t:<22} " + " ".join(f"{v:>4.1f}" for v in vals)
              + f"  {statistics.mean(vals):>4.1f} {statistics.pstdev(vals):>4.1f}")

    glob = [statistics.mean(s.values()) for s in snapshots]
    print("-" * (24 + 5 * len(snapshots) + 12))
    print(f"GLOBAL por run: " + " ".join(f"{g:.1f}" for g in glob))
    print(f"GLOBAL media:   {statistics.mean(glob):.2f}  ± {statistics.pstdev(glob):.2f}")


if __name__ == "__main__":
    main()
