"""leo_code.rag — Retrieval estructural agéntico.

Capas:
- indexer: tree-sitter → cápsulas (símbolos + grafo de llamadas), cache gzip
- agent: tool loop estructural (find_symbol / read_symbol / who_calls / impact …)
- llm: abstracción de modelos (Anthropic, OpenAI/DeepSeek, Ollama, OpenRouter)
- cli: terminal UI con click + rich

Nota: el servidor HTTP (server/) aún expone el path denso heredado (encoder +
vector_store + compressor). Convergerlo a estructural es un follow-up.
"""

__version__ = "0.2.0"
