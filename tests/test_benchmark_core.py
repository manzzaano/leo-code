"""Smoke test: scoring de respuestas contra criterios, judge por LLM inyectado
(sin llamar a ningun LLM real) y el pipeline completo de benchmark_queries."""

from leo_code.core.benchmark import (
    benchmark_queries, llm_judge, print_benchmark_report, score_answer,
)


def test_score_answer_counts_hits_and_misses():
    result = score_answer("La funcion usa cache y grafo.", ["cache", "grafo", "redis"])

    assert result["acertados"] == 2
    assert result["fallados"] == ["redis"]
    assert result["score"] == 0.67


def test_llm_judge_uses_injected_fn_not_a_real_llm():
    assert llm_judge("texto", ["a"], llm_fn=lambda prompt: "SI") is True
    assert llm_judge("texto", ["a"], llm_fn=lambda prompt: "NO") is False


def test_llm_judge_swallows_exceptions_from_llm_fn():
    def _boom(prompt):
        raise RuntimeError("llm caido")

    assert llm_judge("texto", ["a"], llm_fn=_boom) is False


def test_benchmark_queries_runs_end_to_end_with_fake_backends():
    queries = [{"query": "que hace X?", "criterios": ["cache"]}]

    def _run_query_fn(q):
        return {"respuesta": "X usa cache internamente.", "_meta": {"total_tokens": 42}}

    results = benchmark_queries(queries, _run_query_fn, llm_fn=lambda p: "SI")

    assert results[0]["criteria_score"] == 1.0
    assert results[0]["llm_correct"] is True

    print_benchmark_report(results)  # no debe reventar (smoke del reporte impreso)
