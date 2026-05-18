"""Scoring de respuestas contra criterios + LLM judge."""

import re
import unicodedata
from typing import Optional


def score_answer(generated: str, criterios: list[str]) -> dict:
    """Puntúa respuesta contra lista de criterios (tokens que deben aparecer)."""
    def strip_accents(s: str) -> str:
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    gen_lower = strip_accents(generated.lower())
    hits = [c for c in criterios if strip_accents(c.lower()) in gen_lower]
    missed = [c for c in criterios if strip_accents(c.lower()) not in gen_lower]
    score = len(hits) / len(criterios) if criterios else 0
    return {
        "total": len(criterios),
        "acertados": len(hits),
        "acertados_list": hits,
        "fallados": missed,
        "score": round(score, 2),
    }


def llm_judge(
    generated: str,
    criterios: list[str],
    llm_fn,
) -> bool:
    """
    Evalúa si la respuesta cumple la mayoría de los criterios, usando un LLM como juez.
    llm_fn: función (prompt: str) -> str que llama al LLM y retorna la respuesta.
    """
    prompt = f"""Evalua si la respuesta contiene la mayoria de los criterios clave.
No evalues estilo ni formato. SOLO presencia de criterios.
Criterios a buscar: {', '.join(criterios)}
Respuesta: {generated}
Contiene la mayoria de los criterios? Responde SOLO SI o NO."""

    try:
        verdict = llm_fn(prompt).strip().upper()
        return "SI" in verdict or "SÍ" in verdict or "YES" in verdict
    except Exception:
        return False


def benchmark_queries(
    queries: list[dict],
    run_query_fn,
    llm_fn=None,
) -> list[dict]:
    """
    Ejecuta un benchmark completo.
    queries: [{"query": str, "criterios": [str]}, ...]
    run_query_fn: (query: str) -> {"respuesta": str, ...}
    llm_fn: opcional, para LLM judge.
    Retorna lista de resultados con métricas.
    """
    results = []
    for q in queries:
        response = run_query_fn(q["query"])
        criteria_score = score_answer(response.get("respuesta", ""), q.get("criterios", []))
        llm_correct = None
        if llm_fn:
            llm_correct = llm_judge(response.get("respuesta", ""), q.get("criterios", []), llm_fn)
        results.append({
            "query": q["query"],
            "respuesta": response.get("respuesta", ""),
            "criteria_score": criteria_score["score"],
            "criteria_hits": criteria_score["acertados"],
            "criteria_total": criteria_score["total"],
            "llm_correct": llm_correct,
            "meta": response.get("_meta", {}),
        })
    return results


def print_benchmark_report(results: list[dict], baseline_tokens: int = 0):
    """Imprime reporte de benchmark en consola."""
    total_criterios = sum(r["criteria_total"] for r in results)
    total_hits = sum(r["criteria_hits"] for r in results)
    llm_correct = sum(1 for r in results if r.get("llm_correct"))
    total_tokens = sum(r["meta"].get("total_tokens", r["meta"].get("tokens_llm", 0)) for r in results)

    print("\n" + "=" * 80)
    print("BENCHMARK")
    print("=" * 80)
    print(f"\nQueries: {len(results)}")
    if baseline_tokens:
        print(f"Tokens: {total_tokens:,} vs {baseline_tokens:,} baseline ({baseline_tokens/total_tokens:.1f}x)" if total_tokens else f"Tokens: {total_tokens:,}")
    print(f"Cobertura criterios: {total_hits}/{total_criterios} ({total_hits/total_criterios:.0%})" if total_criterios else "Cobertura: N/A")
    if llm_fn := any(r.get("llm_correct") is not None for r in results):
        print(f"LLM judge: {llm_correct}/{len(results)} ({llm_correct/len(results):.0%})")

    print("\n" + "-" * 100)
    print(f"{'Query':<50} {'Crit':>6} {'LLM':>6}")
    print("-" * 100)
    for r in results:
        llm_str = "CORRECTA" if r.get("llm_correct") else ("INCORRECTA" if r.get("llm_correct") is not None else "N/A")
        print(f"{r['query'][:49]:<50} {r['criteria_score']:>5.0%} {llm_str:>9}")
