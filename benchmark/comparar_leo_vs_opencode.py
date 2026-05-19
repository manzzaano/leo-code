"""Comparacion leo-code (KC-RAG) vs opencode CLI usando datos de runs/ existentes."""
import json
import re
from pathlib import Path

BENCH_DIR = Path(__file__).parent
RUNS_DIR = BENCH_DIR / "runs"
RESULTS_FILE = BENCH_DIR / "agent_results.json"
TASKS_FILE = BENCH_DIR / "agent_tasks.json"
N_TASKS = 6


def score_response(response: str, criterios: list[str]) -> float:
    """Keyword matching identico al de kc_core.benchmark.score_answer."""
    if not criterios:
        return 0.0
    texto = response.lower()
    matched = sum(1 for c in criterios if c.lower() in texto)
    return matched / len(criterios)


def load_run(prefix: str, task_idx: int) -> dict:
    path = RUNS_DIR / f"{prefix}_t{task_idx}_r1.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))

    task_results = results["results"]
    assert len(task_results) == N_TASKS == len(tasks)

    # Construir tabla por tarea
    rows = []
    for i, (task_data, task_def) in enumerate(zip(task_results, tasks), start=1):
        criterios = task_def["criterios"]
        task_type = task_def["type"]
        query_short = task_def["query"][:55] + "..." if len(task_def["query"]) > 55 else task_def["query"]

        # Leo — criteria ya calculado en el benchmark original (sobre respuesta completa)
        leo = task_data["leo"]
        leo_criteria = leo["criteria"]
        leo_tokens = leo["tokens"]
        leo_judge = leo.get("judge", None)

        # opencode — puntuamos la respuesta guardada (puede estar truncada ~500 chars)
        oc_run = load_run("oc", i)
        oc_response = oc_run.get("response", "")
        oc_in_tokens = oc_run.get("input_tokens", 0)
        oc_out_tokens = oc_run.get("output_tokens", 0)
        oc_tokens = oc_in_tokens + oc_out_tokens
        oc_criteria = score_response(oc_response, criterios) if oc_response else None

        # no_ctx — baseline sin contexto
        no_ctx = task_data["no_ctx"]
        no_criteria = no_ctx["criteria"]

        rows.append({
            "idx": i,
            "query_short": query_short,
            "type": task_type,
            "criterios": criterios,
            "leo_criteria": leo_criteria,
            "leo_tokens": leo_tokens,
            "leo_judge": leo_judge,
            "oc_criteria": oc_criteria,
            "oc_tokens": oc_tokens,
            "oc_response_len": len(oc_response),
            "no_criteria": no_criteria,
        })

    # === TABLA POR TAREA ===
    print("\n" + "=" * 90)
    print("  COMPARACION: leo-code (KC-RAG) vs opencode CLI vs sin-contexto")
    print("  Fuente: benchmark/runs/ + agent_results.json")
    print("=" * 90)
    print(f"\n{'#':<3} {'Tarea (tipo)':<35} {'Criterios':<28}  {'LEO':>6} {'OC':>6} {'DELTA':>7} {'noctx':>6}")
    print("-" * 90)

    for r in rows:
        crit_str = ", ".join(r["criterios"])[:26]
        leo_pct = r["leo_criteria"] * 100
        no_pct = r["no_criteria"] * 100
        oc_pct = r["oc_criteria"] * 100 if r["oc_criteria"] is not None else None

        if oc_pct is not None:
            delta = leo_pct - oc_pct
            delta_str = f"{delta:+.0f}pp"
            oc_str = f"{oc_pct:.0f}%"
        else:
            delta_str = "N/D"
            oc_str = "N/D"

        label = f"T{r['idx']} {r['query_short'][:28]} ({r['type'][:8]})"
        print(f"{r['idx']:<3} {label:<35} {crit_str:<28}  {leo_pct:>5.0f}% {oc_str:>5} {delta_str:>7} {no_pct:>5.0f}%")

    # === RESUMEN GLOBAL ===
    leo_avg = sum(r["leo_criteria"] for r in rows) / N_TASKS * 100
    no_avg = sum(r["no_criteria"] for r in rows) / N_TASKS * 100
    oc_rows = [r for r in rows if r["oc_criteria"] is not None]
    oc_avg = sum(r["oc_criteria"] for r in oc_rows) / len(oc_rows) * 100 if oc_rows else None

    leo_tok_avg = sum(r["leo_tokens"] for r in rows) / N_TASKS
    oc_tok_avg = sum(r["oc_tokens"] for r in rows) / N_TASKS

    metrics = results["metrics"]
    leo_latency = metrics["latency"]["leo"]
    no_latency = metrics["latency"]["no_ctx"]
    leo_judge_ok = metrics["judge_ok"]["leo"]
    no_judge_ok = metrics["judge_ok"]["no_ctx"]

    print("\n" + "=" * 90)
    print("  RESUMEN GLOBAL")
    print("=" * 90)

    print(f"\n  {'Metrica':<35} {'leo-code':>12} {'opencode':>12} {'sin-ctx':>10}")
    print(f"  {'-'*70}")

    # Criteria %
    oc_avg_str = f"{oc_avg:.1f}%" if oc_avg is not None else "N/D"
    print(f"  {'Criteria promedio (keyword match)':<35} {leo_avg:>11.1f}% {oc_avg_str:>12} {no_avg:>9.1f}%")

    # Delta vs opencode
    if oc_avg is not None:
        delta_oc = leo_avg - oc_avg
        delta_no = leo_avg - no_avg
        print(f"  {'Delta vs opencode':<35} {delta_oc:>+11.1f}pp {'':>12} {'':>10}")
        print(f"  {'Delta vs sin-contexto':<35} {delta_no:>+11.1f}pp {'':>12} {'':>10}")

    # Tokens
    if oc_tok_avg > 0:
        tok_ratio_oc = leo_tok_avg / oc_tok_avg if oc_tok_avg else 0
        print(f"  {'Tokens promedio por tarea':<35} {leo_tok_avg:>11.0f}  {oc_tok_avg:>11.0f}  {'':>9}")
        print(f"  {'  Ratio leo/opencode':<35} {tok_ratio_oc:>11.2f}x {'':>12} {'':>10}")

    # Latencia
    print(f"  {'Latencia promedio (s)':<35} {leo_latency:>11.2f}s {'N/D':>12} {no_latency:>9.2f}s")

    # Judge
    judge_label = f"LLM judge OK / {N_TASKS} tareas"
    print(f"  {judge_label:<35} {leo_judge_ok:>10}/{N_TASKS}  {'N/D':>12} {no_judge_ok:>8}/{N_TASKS}")

    # === NOTAS METODOLOGICAS ===
    print("\n" + "=" * 90)
    print("  NOTAS METODOLOGICAS")
    print("=" * 90)
    print("""
  [1] LEO criteria: puntuados sobre respuesta COMPLETA durante ejecucion original del benchmark.
  [2] OC criteria:  puntuados sobre respuesta GUARDADA en runs/ (~500 chars truncados).
      => OC scores pueden estar SUBESTIMADOS si palabras clave aparecen tras el truncado.
  [3] OC tokens:    input+output tokens del archivo runs/oc_t{n}_r1.json.
      OC input_tokens muy bajos (15-27) vs leo (355+) porque opencode no indexa el repo.
  [4] OC latencia:  no disponible en runs/ — no comparada.
  [5] OC judge:     LLM judge no ejecutado para opencode — no disponible.
  [6] Leo accede al repo via KC-RAG sidecar; opencode no tiene acceso al codigo fuente
      en estas ejecuciones (preguntas sobre bfs_subgraph, capa2.py, pipeline.py).
      Esto explica los input_tokens muy bajos de opencode y respuestas genericas.
""")

    # === INTERPRETACION ===
    print("=" * 90)
    print("  INTERPRETACION")
    print("=" * 90)
    if oc_avg is not None:
        delta_oc = leo_avg - oc_avg
        print(f"""
  leo-code supera a opencode en criterios en {delta_oc:+.1f}pp ({leo_avg:.1f}% vs {oc_avg:.1f}%).
  La ventaja principal es el acceso al codigo fuente via KC-RAG:
    - Tareas de codigo (bfs_subgraph, pipeline.py): opencode responde de forma generica.
    - Tareas de dominio (descuentos, jubilados): opencode sin contexto no conoce las reglas.
  Leo usa ~{leo_tok_avg:.0f} tokens/tarea vs ~{oc_tok_avg:.0f} de opencode.
  El mayor consumo de leo es el coste del contexto KC-RAG (recuperacion de codigo relevante).
""")


if __name__ == "__main__":
    main()
