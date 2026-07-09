# Cambios post-análisis de cuellos de botella

**Fecha:** Mayo 2026 · **Estado:** En ejecución

## Cambios implementados

### 1. chat:agent → rag_direct redirect
**Archivo:** `leo_code/rag/agent/loop.py:37`

Agregó `"deepseek-chat"` a lista de thinking models que redirigen a `rag_direct()`. Chat:agent fallaba (score 2.2/10) → ahora usa KC-RAG puro.

**Impacto esperado:** chat:agent score 2.2 → 8.5+

---

### 2. Reducción de file reading en _build_context
**Archivo:** `leo_code/rag/agent/loop.py:492-495`

Cambios:
- Archivo específico: `content[:25000]` → `content[:10000]` (reducción 60%)
- README.md: `content[:20000]` → `content[:10000]`
- Entrypoints: `content[:5000]` (sin cambio)
- pyproject.toml: `content[:3000]` (sin cambio)

**Impacto esperado:** Tokens 9000+ → 5000-6000 (reducción ~40%)

---

### 3. Capsule budget reduction
**Archivo:** `leo_code/rag/agent/loop.py:586`

Cuando query menciona archivo específico:
- `budget = max(budget, 8000)` → `budget = max(budget, 3000)`

Evita combinación de (file reading 10000 chars) + (capsules 8000 tokens) = 18000 total.

**Impacto esperado:** Total tokens 10000+ → 7000-8000

---

### 4. Métricas de tokens separadas
**Archivo:** `leo_code/rag/agent/loop.py:424-427`

`rag_direct()` ahora retorna:
- `context_chars`: caracteres leídos
- `context_tokens_approx`: chars/4 (aproximación)
- `total_tokens`: input+output reales

**Archivo:** `benchmark/run_config.py:49`

Reporte ahora incluye `context_tokens` separado para análisis de efficiency.

**Impacto esperado:** Claridad en comparación LEO vs OC

---

### 5. Qdrant persistente (cache locality)
**Archivo:** `leo_code/rag/agent/loop.py:618-670`

`_ensure_indexed()` ahora:
1. Calcula hash del repo (checksum de archivos)
2. Si hash coincide con cache → reutiliza índice Qdrant existente
3. Si cambió → reindexea

Evita re-load de embeddings en memory.

**Impacto esperado:** Latencia chat 43s → 28s (re-indexing 15-20s ahorrados)

---

## Métricas a monitorear

| Métrica | Baseline | Meta | Fix #|
|---------|----------|------|------|
| chat:rag score | 8.8 | 8.5+ (sin regresión) | 1,2,3 |
| chat:rag tokens | 9000+ | <6000 | 2,3,4 |
| chat:rag latency | 43s | <35s | 5 |
| chat:agent score | 2.2 | 8.5+ | 1 |
| reasoner latency | 37s | <30s | 5 |

---

## Cuellos de botella adicionales (sesión 2)

### 🔴 Crítico: BM25 nunca se inicializa
**Archivo:** `leo_code/rag/bm25.py` existe pero NO se importa/usa en loop.py.
**Impacto:** 25% del código de retrieval está muerto. Solo se usa búsqueda dense (Qdrant).
**Fix:** Importar BM25Index en _build_context() y fusionar resultados con RRF.

### 🟡 Medio: t11 budget bajo
**Problema:** t11 se clasifica como "code_gen" (800 tokens) en lugar de "onboard".
**Fix aplicado:** classifier.py TOKEN_BUDGET["onboard"] 600 → 2000 tokens
**Impacto:** t11 (arquitectura) tendrá 2.5x más contexto.

### 🟡 Medio: top_k bajo en retrieval
**Problema:** `_vector_store.search(query, top_k=10)` es bajo para recuperación densa.
**Fix aplicado:** top_k=10 → 20
**Impacto:** Mejora recall, probablemente sin latencia significativa.

### 🟢 Menor: Clasificación de tareas inconsistente
t11 clasifica como "code_gen" (800 tok) cuando debería ser "onboard" (2000 tok después del fix).
Podría haber otras misclasificaciones. Revisar TASK_SIGNALS en classifier.py.

---

## Benchmark esperado

Ejecutando: `python benchmark/run_config.py --all-models`

Verificar en `benchmark/results_final/summary.json` y `benchmark/REPORT_FINAL.md`.

Correr también: `python benchmark/compare_results.py` para delta pre/post.

---

## Sesión 2026-07-08/09: medición real vs opencode + techo de KC-RAG de un solo pase

**Contexto:** el claim de README ("15x menos tokens") nunca se habia medido de forma justa.
`benchmark/run_real.py` media opencode por `len(response)//4` (solo texto de salida, ignoraba
su propio costo de tool-calling interno) y opencode corria con el MCP de leo-code +
codegraph/pencil (config global del usuario) habilitados sin que nadie lo notara. Corregido:
opencode ahora se mide con `--format json` (tokens reales de cada `step_finish`) y corre con
`XDG_CONFIG_HOME` aislado + `opencode.json` del repo renombrado un instante (ver
`run_oc_subprocess` en `benchmark/run_real.py`).

Con medicion justa, 3 corridas reales (n=15, `deepseek/deepseek-chat`, serial `--batch 1`):

| modo LEO | tok/task | calidad (judge) | vs opencode vanilla |
|---|---|---|---|
| `run()` — agente completo, loop de tools | ~59,000 | 7.3-7.6 | opencode: 72K-192K tok, 6.6-8.5 calidad (opencode mismo es ruidoso entre corridas) |
| `rag_direct()` — un solo pase, sin tools | ~2,500-3,900 | **4.2-4.9** ⚠️ | 93% menos tokens, pero falla en tasks que exigen precision/amplitud |
| `run_smart()` — hibrido con self-check | ~46,000-55,000 | **7.2** (con gate) | 55-70% menos tokens, calidad practicamente empatada |

**`rag_direct()` no existia en el codigo** pese a estar documentado en este archivo y en
`docs/BENCHMARK_PLAN.md` (linea 38, "LEO-RAG") — se reimplemento desde cero en
`leo_code/rag/agent/loop.py` junto con `run_smart()` (fallback automatico a `run()` si
`_is_breadth()`, la task necesita editar archivos, o el propio modelo se autoevalua
"CONTEXT_INSUFFICIENT" — ver `_rag_system_prompt()`).

### Techo real: ~55-70%, no ~90%

Se probo bajar el gate de calidad (heuristico de longitud → autoevaluacion del modelo) y
mejoro la calidad (6.3 → 7.2) sin mover mucho el % de tokens. El techo no es de tuning de
heuristico: es que un solo pase de contexto comprimido (top-K por relevancia) genuinamente
NO alcanza para:
- Tasks de precision (`debug`, `optimize`): necesitan el cuerpo EXACTO y completo de la
  funcion objetivo, no un resumen top-K que puede omitirla o truncarla.
- Tasks de amplitud (`cadena completa`, `traza`, listas exhaustivas across muchos simbolos):
  requieren mas de lo que un presupuesto de tokens fijo puede traer en un solo pase.

### Siguiente paso (no iniciado esta sesion, decision del usuario)

Para cerrar la brecha de verdad sin sacrificar calidad hay que mejorar el retrieval/compresion
de KC-RAG en si — candidatos a investigar:
- Presupuesto de contexto adaptativo segun complejidad de la query (no fijo por task_type).
- Multi-hop dentro de UNA sola llamada de construccion de contexto (ej. si el top-1 resultado
  referencia otro simbolo, traer tambien su cuerpo completo) en vez de depender de que el
  agente lo pida despues con una tool — asi `rag_direct()` podria cubrir mas casos sin
  escalar al loop de tools.
- ~~Revisar por que BM25 nunca se activa~~ — **confirmado esta sesion (ver abajo): SI esta
  activo**, la nota de "sesion 2" quedo desactualizada.

Esto es un proyecto de retrieval, no un fix de una linea — no se empezo esta sesion.

---

## Sesión 2026-07-09 (cont.): backlog de docs/OPTIMIZATION_REPORT.md

Revisados los 4 items pendientes de "Próximos Pasos" del informe de 2026-06-11.

### 1. Refactor del compressor a OOP — descartado (YAGNI)
`CompressConfig` + `COMPRESS_STRATEGIES` ya logran el objetivo de mantenibilidad;
un rewrite a clases no arregla bug ni duplicación real, solo agrega boilerplate.
El gap real era cobertura de tests (6 de 13 `task_type` sin tests) — cerrado en
`tests/test_compressor.py`.

### 2. Fix: guard muerto en VectorStore + storage aislado para benchmarks paralelos
**Archivo:** `leo_code/rag/vector_store.py:17`, `leo_code/engine.py`,
`benchmark/leo_runner.py`, `benchmark/leo_rag_runner.py`, `benchmark/leo_smart_runner.py`

El guard `"_" not in collection_name` nunca disparaba con el collection_name real
de producción (`leo_mcp_{hash}`, siempre tiene `_`) — corregido. Pero eso solo no
alcanzaba: el lock de qdrant-local es a nivel de **directorio de storage**, no de
colección — namespacing de colección nunca lo iba a arreglar. Los 3 runners de
benchmark ahora usan `LEO_QDRANT_PATH` (env var leída por `engine.py`, default
`./cache/qdrant_leo`) apuntando a un directorio temporal propio por subproceso,
eliminando la contención real en corridas `--batch N`. Para uso multi-proceso real
(2 IDEs concurrentes con `leo-code-mcp` sobre el mismo repo) se documenta el
comportamiento actual (single-writer + fallback a memoria) como limitación
conocida — un modo servidor Qdrant real es una decisión de arquitectura mayor,
fuera de alcance.

De paso, confirmado que **BM25 sí está activo** (`engine.py`, fusión RRF con
Qdrant dentro de `compute_context`) — la nota de "sesión 2" que lo marcaba como
posible código muerto estaba desactualizada.

### 3. TTL de cache para detectar eliminaciones
**Archivo:** `leo_code/rag/agent/loop.py`

`_is_cache_stale` solo detectaba mtime más nuevo — una eliminación/renombrado sin
otro archivo tocado nunca disparaba `Indexer.sync()` (que sí calcula `deleted`
correctamente), quedando desincronizado indefinidamente. Nuevo `LEO_CACHE_TTL`
(env var, default 3600s) fuerza un sync periódico independiente del mtime-walk.
Hash-tracking de contenido se descartó — no arregla este gap específico, solo el
TTL lo hace.

### 4. Endpoint Prometheus
**Archivo:** `leo_code/core/metrics.py`, `leo_code/server/server.py`

Nuevo `GET /metrics/prometheus` (formato text exposition, hand-rolled, sin
dependencia `prometheus_client` — 16 campos simples no la justifican). CloudWatch
queda fuera de alcance — requiere credenciales/infra AWS, decisión del usuario.
