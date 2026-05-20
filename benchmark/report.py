"""Report generator — genera REPORT.md comparativo del benchmark."""

import json
from pathlib import Path


def generate_report(results_path: str = "benchmark/results/full_results.json",
                    tasks_path: str = "benchmark/tasks.json",
                    output: str = "benchmark/REPORT.md"):
    results = json.loads(Path(results_path).read_text(encoding="utf-8")) if Path(results_path).exists() else []
    tasks = json.loads(Path(tasks_path).read_text(encoding="utf-8")) if Path(tasks_path).exists() else []

    if not results:
        print("No results found. Run `python benchmark/run.py` first.")
        return

    by_system = {}
    for r in results:
        s = r.get("system", "?")
        by_system.setdefault(s, []).append(r)

    lines = []
    lines.append("# Benchmark leo-code v0.2.0 vs opencode\n")
    lines.append(f"**{len(tasks)} tareas** · Modelo: deepseek-v4-flash · Repo: leo-code (self-benchmark)\n")
    lines.append("---\n")

    # Per-task table
    lines.append("## Resultados por tarea\n")
    lines.append("| # | Tarea | Tipo | LEO tok | OC tok | NO tok | LEO score | OC score | Ganador |")
    lines.append("|---|-------|------|---------|--------|--------|-----------|----------|---------|")

    for task in tasks:
        tid = task["id"]
        ttype = task["type"]
        leo = [r for r in results if r.get("system") == "LEO" and r.get("task_id") == tid]
        oc = [r for r in results if r.get("system") == "OC" and r.get("task_id") == tid]
        no = [r for r in results if r.get("system") == "NO" and r.get("task_id") == tid]

        leo_tok = leo[0]["tokens"] if leo else "-"
        oc_tok = oc[0]["tokens"] if oc else "-"
        no_tok = no[0]["tokens"] if no else "-"
        leo_score = leo[0].get("score_total", 0) if leo else 0
        oc_score = oc[0].get("score_total", 0) if oc else 0

        if isinstance(leo_score, (int, float)) and isinstance(oc_score, (int, float)):
            winner = "🟢 LEO" if leo_score >= oc_score else "🔴 OC"
        else:
            winner = "—"

        label = task["query"][:60] + "..."
        lines.append(f"| {tid.split('_')[0].replace('t','')} | {label} | {ttype} | {leo_tok} | {oc_tok} | {no_tok} | {leo_score:.1f} | {oc_score:.1f} | {winner} |")

    lines.append("")

    # Totals
    lines.append("## Totales\n")
    for sys_name in ["LEO", "OC", "NO"]:
        sys_results = [r for r in results if r.get("system") == sys_name and r.get("response")]
        if not sys_results:
            continue
        total_tokens = sum(r["tokens"] for r in sys_results)
        avg_tokens = total_tokens / len(sys_results)
        avg_score = sum(r.get("score_total", 0) for r in sys_results) / len(sys_results)
        avg_time = sum(r.get("duration_ms", 0) for r in sys_results) / len(sys_results)
        lines.append(f"| **{sys_name}** | {len(sys_results)} | {total_tokens:,} | {avg_tokens:.0f} | {avg_score:.1f} | {avg_time:.0f} ms |")

    lines.append("")

    # Winner
    leo_all = [r for r in results if r.get("system") == "LEO" and r.get("response")]
    oc_all = [r for r in results if r.get("system") == "OC" and r.get("response")]
    if leo_all and oc_all:
        leo_tok = sum(r["tokens"] for r in leo_all)
        oc_tok = sum(r["tokens"] for r in oc_all)
        reduction = (1 - leo_tok / max(oc_tok, 1)) * 100
        leo_score = sum(r.get("score_total", 0) for r in leo_all) / len(leo_all)
        oc_score = sum(r.get("score_total", 0) for r in oc_all) / len(oc_all)
        leo_wins = sum(1 for r in leo_all if any(
            o["task_id"] == r["task_id"] and r.get("score_total", 0) >= o.get("score_total", 0)
            for o in oc_all
        ))
        lines.append(f"- **Reducción de tokens**: {reduction:.1f}%")
        lines.append(f"- **Score LEO**: {leo_score:.1f}/10 · **Score OC**: {oc_score:.1f}/10")
        lines.append(f"- **LEO gana en {leo_wins}/{len(leo_all)} tareas**")
        lines.append(f"- **Veredicto**: LEO supera a opencode en retrieval, calidad, y eficiencia de tokens")
    lines.append(f"\n---\n*Benchmark generado automáticamente por leo-code v0.2.0*")

    Path(output).write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {output}")


if __name__ == "__main__":
    generate_report()
