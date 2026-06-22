# KC-RAG → Retrieval estructural agéntico (rediseño)

**Fecha:** 2026-06-22
**Estado:** Implementado (Enfoque 1). Benchmark en validación.

## Contexto / problema

`leo-code` es un agente de terminal cuyo diferenciador era **KC-RAG**: indexar el
repo en "cápsulas" (símbolos) y **pre-inyectar** un contexto comprimido al LLM.

El sistema peleaba consigo mismo: hacía retrieval denso pesado (embeddings →
Qdrant + BM25 + cross-encoder rerank + clustering DBSCAN → blob comprimido) **y
además** daba tools al agente. El benchmark mostró que el agente **ignora el blob**
y explora con sus tools igual → se paga doble. El score se estancó en ~5.0/10 y el
path paralelo crasheaba por el lock de Qdrant. Diagnóstico: el stack denso era
"RAG-para-docs" mal aplicado a código; el cuello real era la capa agente, no el
retrieval.

**Criterio de éxito:** máxima eficiencia tokens/coste manteniendo respuestas útiles.

## Decisión

Eliminar el retrieval denso. Adoptar el paradigma de agentes de código modernos:
**índice estructural barato (grafo de símbolos) + tools precisas, sin seed**. El LLM
conduce el retrieval on-demand; los tokens se ahorran devolviendo símbolos exactos
en vez de archivos enteros, y no inyectando ningún blob.

## Arquitectura

**Índice (conservado, sin embeddings):** `core/parser.py` (cápsulas: firma, cuerpo,
docstring, calls, imports), `core/graph.py` (grafo de llamadas), `indexer/watcher.py`
(build + cache `.leo-code/kc_index.json.gz`, warm <1s). En memoria.

**Retrieval = tools estructurales** (`rag/agent/tools.py`), backed por el índice:
- `find_symbol(pattern|name)` — localiza símbolos (nombre/tipo/file:line/firma).
- `read_symbol(name)` — cuerpo de UN símbolo (no archivo entero). Clave del ahorro.
- `who_calls` / `callees` — aristas directas del grafo.
- `impact(name)` — callers transitivos (BFS).
- `search_code` (grep, líneas), `read_file` con cap >200 líneas + rango start/end.
- Edición/exec/tests/git sin cambios.

**Agente (`rag/agent/loop.py`):** cero seed — `_build_context` solo asegura el índice
y lo cablea a las tools (`tools.set_index`), devuelve `""`. System prompt instruye a
descubrir vía tools estructurales. Síntesis final (`_finalize`) fuerza una respuesta
sin tools, anclada a la pregunta original, cuando el agente no concluye solo.

**Provider (`rag/llm/openai_adapter.py`):** fallback que parsea tool-calls que
DeepSeek a veces emite como markup DSML en el texto (`_parse_dsml_tool_calls`).

**Borrado:** `encoder`/`vector_store`/`reranker`/`semantic_clustering`/
`synthetic_edge_synthesizer`/`cluster_serializer`/`expander` del path del agente,
`__init__.retrieve()`, `_exact_match`/`_rrf_fuse`. (El servidor HTTP `server/` aún usa
encoder/vector_store/compressor/bm25 → convergerlo es follow-up; hasta entonces las
deps qdrant/sentence-transformers se mantienen.)

## Flujo de datos

```
leo ask "..." → AgentLoop.run
  → índice warm (parse 1 vez, cache gzip), cableado a tools
  → LLM recibe SOLO query + catálogo de tools (sin contexto inyectado)
  → loop: find_symbol → read_symbol → who_calls → … (resultados capados 800 chars)
  → concluye solo, o _finalize fuerza síntesis tras N iteraciones
```

## Errores

Tools devuelven `[Error: ...]`/`[no encontrado]` legible (nunca excepción cruda).
`_finalize` y el parser DSML van envueltos en try/except con fallback.

## Testing / medición

- `pytest` (regresión; contrato `_build_context → (context, timings)` intacto).
- Benchmark `benchmark/run_real.py` (juez LLM 0-10) contra **copia temporal** del repo
  (tasks de edición no tocan el repo real). Secuencial, `PYTHONUTF8=1`.

## Resultados (subset t1,t8,t11,t12, secuencial)

| Versión | Score | Latencia |
|---|---|---|
| baseline (clustering) | ~5.0 (irreproducible) | 43s |
| estructural sin embeddings | 4.9 | 19s |
| + fix parsing DSML | 4.7 | 25s |
| + fix síntesis final | **6.9** | 35s |

4/4 tareas completan con respuesta real (t11 onboard 1.0 → 7.3). Cero embeddings →
indexado instantáneo, escala a monorepos.

## Follow-ups

1. Convergir `server/get_context` a estructural → permite quitar deps
   qdrant/sentence-transformers/torch.
2. t1 (4.5): el agente sobre-explora en tareas de explicación; afinar prompt/heurística.
3. Migrar índice a SQLite+FTS5 si el tamaño de repo lo pide (escala).
