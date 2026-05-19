"""leo_code.rag — Pipeline de retrieval estructural (encoding → search → expand → rerank → compress).

Capas:
- indexer: tree-sitter + watchdog → cápsulas → Qdrant
- kc_rag: encoding → vector search → graph expand → rerank → compress
- llm: abstracción de modelos (Anthropic, OpenAI, Ollama, OpenRouter)
- agent: tool loop (consulta → KC-RAG → LLM → tools → repeat)
- cli: terminal UI con click + rich
"""

__version__ = "0.1.0"

from leo_code.rag.encoder import Encoder
from leo_code.rag.vector_store import VectorStore
from leo_code.rag.expander import expand
from leo_code.rag.reranker import Reranker
from leo_code.rag.compressor import compress

__all__ = ["Encoder", "VectorStore", "expand", "Reranker", "compress"]


def retrieve(
    query: str,
    encoder: Encoder,
    vector_store: VectorStore,
    reranker: Reranker,
    capsules: dict,
    budget_tokens: int = 40000,
) -> str:
    """Pipeline completo KC-RAG: query → prompt comprimido."""
    emb = encoder.encode(query)
    top_ids = vector_store.search(query, top_k=50)
    expanded = expand(capsules, top_ids, max_depth=2)
    top_15 = reranker.rerank(query, expanded, top_k=15)
    prompt = compress(top_15, list(capsules.values()), budget_tokens)
    return prompt
