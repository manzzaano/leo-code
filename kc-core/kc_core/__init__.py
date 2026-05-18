"""kc_core — Librería compartida para Tiered KG-RAG y KC-Code.

Módulos:
- parser: Extracción de cápsulas de código (AST + tree-sitter)
- graph: BFS traversal, filtro de relaciones, búsqueda en grafo
- context: Serialización compacta de contexto para LLMs
- evidence: Extracción determinista de evidencia (grounding)
- cache: Redis cache L1/L2/L3 con circuit breaker
- benchmark: Scoring de respuestas + LLM judge
"""

from kc_core.parser import Capsule, extract_from_file, extract_from_python, build_call_graph
from kc_core.graph import bfs_subgraph, find_nodes_by_name, detect_relation_filter, filter_by_relation
from kc_core.context import serialize_context
from kc_core.evidence import extract_evidence, verify_grounding
from kc_core.cache import init as cache_init, is_available as cache_available
from kc_core.benchmark import score_answer, llm_judge, benchmark_queries, print_benchmark_report
