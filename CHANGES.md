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
