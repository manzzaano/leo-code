"""kc_code — Agente de terminal model-agnostic con retrieval estructural de código.

Capas:
- indexer: tree-sitter + watchdog → cápsulas → Qdrant
- kc_rag: encoding → vector search → graph expand → rerank → compress
- llm: abstracción de modelos (Anthropic, OpenAI, Ollama, OpenRouter)
- agent: tool loop (consulta → KC-RAG → LLM → tools → repeat)
- cli: terminal UI con click + rich
"""

__version__ = "0.1.0"
