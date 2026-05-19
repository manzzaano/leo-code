"""leo_code — KC-RAG: Recuperación estructural de código por subgrafo de dependencias.

Submódulos:
- leo_code.core: parser AST, grafo BFS, serialización de contexto, cache Redis
- leo_code.rag: pipeline retrieval (encoder, vector store Qdrant, compressor, classifier)
- leo_code.rag.llm: capa model-agnostic (Anthropic, OpenAI, Ollama, OpenRouter)
- leo_code.rag.agent: agent loop (KC-RAG → LLM → tools → repeat)
- leo_code.server: servidor FastAPI KC-RAG (:9898)
"""

__version__ = "0.1.0"
