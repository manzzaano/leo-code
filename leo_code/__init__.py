"""leo_code — KC-RAG: motor de contexto de código estructural, expuesto como servidor MCP.

Submódulos:
- leo_code.engine: indexado persistente + retrieval híbrido + compresión (el motor)
- leo_code.core: parser AST, grafo determinista (where/who_calls/impact/trace/guard), cache Redis
- leo_code.rag: pipeline de retrieval (encoder, vector store Qdrant, compressor, classifier, indexer)
- leo_code.server: servidor MCP (mcp_server.py) + servidor HTTP opcional (server.py)
"""

__version__ = "0.2.0"
