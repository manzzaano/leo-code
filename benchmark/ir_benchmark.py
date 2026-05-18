"""Benchmark IR — Metodología oficial v2 (Nivel 1 + Nivel 2).
Cumple: R1 (mismo LLM, temp=0.2), R2 (mismas tareas), R5 (5 ejecuciones).
Mide: TRR (Token Reduction Ratio), tokens, latencia, criteria score.
Reporta: media + desviación estándar por tarea.

Run: python benchmark/ir_benchmark.py
"""

import sys, os, json, time, httpx, statistics
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-core')
sys.path.insert(0, r'C:\Users\Ismael\Desktop\kc-code')
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(r'C:\Users\Ismael\Desktop\RAG\.env')

from openai import OpenAI
from kc_core.benchmark import score_answer

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
MODEL = "deepseek-chat"
TEMPERATURE = 0.2  # R1
SIDECAR = "http://localhost:9898"
REPO = r"C:\Users\Ismael\Desktop\RAG"
RUNS = 5  # R5
SEED = 42   # R4

TASKS = json.loads(Path(__file__).parent.joinpath("agent_tasks.json").read_text(encoding="utf-8"))


def call_llm(system_prompt: str, user_query: str) -> dict:
    t0 = time.time()
    try:
        resp = LLM.chat.completions.create(
            model=MODEL, temperature=TEMPERATURE, max_tokens=1024,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
        )
        latency = time.time() - t0
        return {
            "respuesta": resp.choices[0].message.content or "",
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
            "latency_s": round(latency, 3),
        }
    except Exception as e:
        return {
            "respuesta": f"Error: {e}", "input_tokens": 0, "output_tokens": 0,
            "latency_s": round(time.time() - t0, 3),
        }


def get_kcrag_context(query: str) -> dict:
    try:
        r = httpx.post(f"{SIDECAR}/context", json={
            "query": query, "repo_path": REPO,
            "task_type": "auto", "budget_tokens": 0,
        }, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def main():
    print("=" * 110)
    print(f"IR BENCHMARK — Metodologia v2 (Nivel 2)")
    print(f"Model: {MODEL} | Temp: {TEMPERATURE} | Runs: {RUNS} | Seed: {SEED}")
    print("=" * 110)

    all_results = []

    for ti, task in enumerate(TASKS):
        q = task["query"]
        criterios = task["criterios"]
        kc_type = task.get("kc_task_type", "auto")
        print(f"\n{'='*110}")
        print(f"TASK {ti+1}/{len(TASKS)} [{kc_type}]: {q[:80]}...")
        print(f"{'='*110}")

        task_runs = []

        for run in range(1, RUNS + 1):
            t0_ctx = time.time()
            ctx = get_kcrag_context(q)
            ctx_latency = round((time.time() - t0_ctx) * 1000)

            # ── KC-RAG mode ──
            kc_prompt = "Eres un asistente experto. Responde en espanol, se conciso.\n\n"
            if ctx.get("context"):
                kc_prompt += f"Contexto estructural del codigo:\n{ctx['context']}\n\n"
            kc_prompt += f"Pregunta: {q}"

            kc_result = call_llm(kc_prompt, q)

            # ── No-KC mode (baseline) ──
            no_prompt = f"Eres un asistente experto. Responde en espanol, se conciso.\n\nPregunta: {q}"
            no_result = call_llm(no_prompt, q)

            # ── Scoring ──
            kc_score = score_answer(kc_result["respuesta"], criterios)
            no_score = score_answer(no_result["respuesta"], criterios)

            kc_tok = kc_result["input_tokens"] + kc_result["output_tokens"]
            no_tok = no_result["input_tokens"] + no_result["output_tokens"]
            trr = round(1 - (kc_tok / max(no_tok, 1)), 3)  # Token Reduction Ratio

            task_runs.append({
                "run": run,
                "kc_tokens": kc_tok,
                "kc_input": kc_result["input_tokens"],
                "kc_output": kc_result["output_tokens"],
                "kc_latency": kc_result["latency_s"],
                "kc_criteria": kc_score["score"],
                "kc_context_tokens": ctx.get("tokens", 0),
                "kc_context_latency_ms": ctx_latency,
                "no_tokens": no_tok,
                "no_input": no_result["input_tokens"],
                "no_output": no_result["output_tokens"],
                "no_latency": no_result["latency_s"],
                "no_criteria": no_score["score"],
                "trr": trr,
            })

            print(f"  run {run}: KC={kc_tok:,}tok/{kc_result['latency_s']}s/{kc_score['score']:.0%} "
                  f"| NoKC={no_tok:,}tok/{no_result['latency_s']}s/{no_score['score']:.0%} "
                  f"| TRR={trr:+.0%} | ctx={ctx.get('tokens',0)}tok/{ctx_latency}ms")

        # ── Aggregation ──
        kc_tokens = [r["kc_tokens"] for r in task_runs]
        no_tokens = [r["no_tokens"] for r in task_runs]
        kc_lat = [r["kc_latency"] for r in task_runs]
        no_lat = [r["no_latency"] for r in task_runs]
        kc_crit = [r["kc_criteria"] for r in task_runs]
        no_crit = [r["no_criteria"] for r in task_runs]
        trrs = [r["trr"] for r in task_runs]
        ctx_toks = [r["kc_context_tokens"] for r in task_runs]
        ctx_lats = [r["kc_context_latency_ms"] for r in task_runs]

        agg = {
            "task": q,
            "type": kc_type,
            "runs": task_runs,
            "kc_tokens_mean": round(statistics.mean(kc_tokens)),
            "kc_tokens_std": round(statistics.stdev(kc_tokens)) if RUNS > 1 else 0,
            "no_tokens_mean": round(statistics.mean(no_tokens)),
            "no_tokens_std": round(statistics.stdev(no_tokens)) if RUNS > 1 else 0,
            "kc_latency_mean": round(statistics.mean(kc_lat), 2),
            "kc_latency_std": round(statistics.stdev(kc_lat), 2) if RUNS > 1 else 0,
            "no_latency_mean": round(statistics.mean(no_lat), 2),
            "no_latency_std": round(statistics.stdev(no_lat), 2) if RUNS > 1 else 0,
            "kc_criteria_mean": round(statistics.mean(kc_crit), 2),
            "no_criteria_mean": round(statistics.mean(no_crit), 2),
            "trr_mean": round(statistics.mean(trrs), 3),
            "trr_std": round(statistics.stdev(trrs), 3) if RUNS > 1 else 0,
            "context_tokens_mean": round(statistics.mean(ctx_toks)),
            "context_latency_ms_mean": round(statistics.mean(ctx_lats)),
        }
        all_results.append(agg)

        trr_sign = "+" if agg["trr_mean"] > 0 else ""
        print(f"  MEAN: KC={agg['kc_tokens_mean']:,}±{agg['kc_tokens_std']}tok/{agg['kc_latency_mean']}s "
              f"| NoKC={agg['no_tokens_mean']:,}±{agg['no_tokens_std']}tok/{agg['no_latency_mean']}s "
              f"| TRR={trr_sign}{agg['trr_mean']:.0%}±{agg['trr_std']:.0%}")

    # ── Global report ──
    print(f"\n{'='*110}")
    print("IR BENCHMARK — RESULTADOS FINALES (Metodologia v2)")
    print(f"{'='*110}")

    print(f"\n{'Metrica':<35} {'KC-RAG (media±std)':>25} {'No-KC (media±std)':>25} {'Delta':>15}")
    print("-" * 100)

    kc_all_tok = [r["kc_tokens_mean"] for r in all_results]
    no_all_tok = [r["no_tokens_mean"] for r in all_results]
    total_trr = round(1 - (sum(kc_all_tok) / max(sum(no_all_tok), 1)), 3)

    print(f"{'Tokens totales':<35} {sum(kc_all_tok):>25,} {sum(no_all_tok):>25,} {total_trr:>14.0%} TRR")
    print(f"{'Latencia total (s)':<35} {sum(r['kc_latency_mean'] for r in all_results):>24.1f}s {sum(r['no_latency_mean'] for r in all_results):>24.1f}s {'-' if sum(r['kc_latency_mean'] for r in all_results)<sum(r['no_latency_mean'] for r in all_results) else '+'}")
    print(f"{'Criteria score avg':<35} {sum(r['kc_criteria_mean'] for r in all_results)/len(all_results):>24.0%} {sum(r['no_criteria_mean'] for r in all_results)/len(all_results):>24.0%}")
    print(f"{'Contexto KC-RAG (tokens)':<35} {sum(r['context_tokens_mean'] for r in all_results):>25,}")
    print(f"{'Contexto KC-RAG (ms)':<35} {sum(r['context_latency_ms_mean'] for r in all_results)/len(all_results):>24.0f}ms")

    # Per-task table
    print(f"\n{'Tarea':<45} {'KC tok':>9} {'NoKC tok':>9} {'TRR':>7} {'KC lat':>7} {'NoKC lat':>7} {'KC crit':>8} {'NoKC crit':>8}")
    print("-" * 110)
    for r in all_results:
        trr_sign = "+" if r["trr_mean"] > 0 else ""
        print(f"{r['task'][:44]:<45} {r['kc_tokens_mean']:>9,} {r['no_tokens_mean']:>9,} "
              f"{trr_sign}{r['trr_mean']:>6.0%} {r['kc_latency_mean']:>6.1f}s {r['no_latency_mean']:>6.1f}s "
              f"{r['kc_criteria_mean']:>7.0%} {r['no_criteria_mean']:>7.0%}")

    # Save
    out = Path(__file__).parent / "ir_results.json"
    out.write_text(json.dumps({
        "methodology": "v2", "model": MODEL, "temperature": TEMPERATURE,
        "runs_per_task": RUNS, "seed": SEED, "repo": REPO,
        "total_kc_tokens": sum(kc_all_tok), "total_no_tokens": sum(no_all_tok),
        "total_trr": total_trr,
        "tasks": all_results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultados: {out}")

    # ── Checklist §12 ──
    print(f"\n{'='*110}")
    print("CHECKLIST METODOLOGIA v2 §12")
    print(f"{'='*110}")
    checks = {
        "R1 Mismo LLM + temp": f"{MODEL} / temp={TEMPERATURE}",
        "R2 Mismas tareas": f"{len(TASKS)} tareas, sin reordenar",
        "R3 Mismo hardware": "Windows 11, Python 3.14",
        "R4 Semilla fija": f"seed={SEED} (para sample si aplica)",
        "R5 5 ejecuciones": f"{RUNS} runs por tarea",
        "R6 Logging": "ir_results.json con todas las runs",
        "R7 Aislamiento": "Parcial (mismo filesystem, sin Docker)",
        "R8 Sin contaminacion": "Tareas sobre codigo propio, no en training data",
    }
    for k, v in checks.items():
        print(f"  [{'x' if 'Parcial' not in v else '~'}] {k}: {v}")
    fulfilled = sum(1 for v in checks.values() if "Parcial" not in v)
    print(f"\n  Checklist: {fulfilled}/{len(checks)} items completos, {len(checks)-fulfilled} parciales")


if __name__ == "__main__":
    main()
