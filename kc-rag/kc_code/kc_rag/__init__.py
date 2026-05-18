"""KC-RAG: Pipeline de retrieval estructural (encoding → search → expand → rerank → compress)."""

from kc_code.kc_rag.encoder import Encoder
from kc_code.kc_rag.vector_store import VectorStore
from kc_code.kc_rag.expander import expand
from kc_code.kc_rag.reranker import Reranker
from kc_code.kc_rag.compressor import compress

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
