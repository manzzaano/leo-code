# kc-code

Librería KC-RAG: recuperación estructural de código por subgrafo de dependencias.

Parte del sistema [leo-code](https://github.com/manzzaano/leo-code).

## Componentes

- **Indexer** — parsea Python con AST, extrae cápsulas (función/clase/módulo) con metadatos
- **VectorStore** — índice Qdrant HNSW con embeddings `all-MiniLM-L6-v2`
- **Compressor** — compresión adaptativa por tipo de tarea (code_query, refactor, search, code_gen)
- **AgentLoop** — bucle iterativo: KC-RAG → LLM → tool calls → iteración
- **LLM** — capa model-agnostic: Anthropic, OpenAI/DeepSeek, Ollama, OpenRouter

## Instalación

```bash
pip install kc-code
```

## Licencia

MIT — Ismael Manzano León
