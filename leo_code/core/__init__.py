"""leo_code.core — Librería compartida para KC-RAG.

Módulos:
- parser: Extracción de cápsulas de código (AST + tree-sitter)
- graphquery: Queries estructurales con prueba (where/who_calls/impact/trace/guard)
- context: Serialización compacta de contexto para LLMs
- evidence: Extracción determinista de evidencia (grounding)
- cache: Redis cache L1/L2/L3 con circuit breaker
- benchmark: Scoring de respuestas + LLM judge
"""

from leo_code.core.parser import Capsule, extract_from_file, extract_from_python, build_call_graph
from leo_code.core.context import serialize_context
from leo_code.core.evidence import extract_evidence, verify_grounding
from leo_code.core.cache import init as cache_init, is_available as cache_available
from leo_code.core.benchmark import score_answer, llm_judge, benchmark_queries, print_benchmark_report
