# M2.5 — Hardening del núcleo leo-mcp (tests + dedup)

**Fecha:** 2026-09-10 · **Hito:** M2.5 (nuevo, pausa explícita de M2)

## Objetivo

Preparar el núcleo de **leo-mcp** (el producto a entregar, no el agente TUI) para
v1: cobertura de smoke test en todos los módulos del camino crítico + auditoría
de código duplicado/redundante en el paquete `core/`.

## Alcance

**Dentro de alcance** — núcleo leo-mcp (lo que ejecuta `get_context`/`graph` vía
MCP): `engine.py`, `filectx.py`, `core/*`, `rag/bm25.py`, `rag/classifier.py`,
`rag/compressor.py`, `rag/encoder.py`, `rag/scorer.py`, `rag/vector_store.py`,
`rag/indexer/*`, `server/mcp_server.py`, `server/server.py`.

**Fuera de alcance** — agente TUI (PLAN.md: "no es el foco del cierre"):
`rag/agent/*`, `rag/cli/*`, `rag/llm/*` (13 adaptadores de proveedor),
`plugins/*`, `meter/*`, `tui/*`, `rag/conversation_history.py`.

De los 63 módulos totales de `leo_code/`, ~25 caen dentro de alcance. De esos,
**206 tests existentes ya cubren 17**; quedan **8 sin test**:

| Módulo | Motivo de prioridad |
|---|---|
| `engine.py` | Motor KC-RAG (`compute_context`, indexado) — crítico, cero tests directos hoy |
| `filectx.py` | Swap usado por el hook `PostToolUse` de Claude Code (`.claude/hooks/leo-read-swap.py`) |
| `core/cache.py` | Usado por `engine._cache_context_result` / `_invalidate_cache` |
| `core/evidence.py` | Usado por `core/guardian.py` (citas archivo:línea) |
| `core/tokens.py` | Conteo de tokens — usado en presupuestos de `compressor` |
| `core/parser_generic.py` | Fallback de parseo para lenguajes sin parser dedicado |
| `core/benchmark.py` | `score_answer`/`llm_judge` — usado por el harness de benchmark |
| `core/orggraph.py` | Grafo multi-repo, CLI standalone — prioridad más baja |

`logging_config.py` queda excluido: es un one-liner de setup, sin lógica que
falsear.

## Fase 1 — Smoke tests

Convención (igual que `tests/test_vector_store_lock.py`): funciones sueltas
con pytest, sin clases, docstring de 1 línea solo si el "por qué" no es obvio,
`tmp_path`/fixtures mínimas. Un archivo `tests/test_<modulo>.py` por módulo.

Nivel: **smoke**, no exhaustivo — import limpio + llamada con input típico +
no explota + resultado tiene la forma esperada. Detectar roturas gordas, no
perseguir cada edge case.

Orden: de mayor a menor criticidad según la tabla de arriba (`engine.py`
primero).

**Hecho cuando:** los 8 módulos tienen al menos 1 test, `pytest tests/ -q`
sigue en verde (206 + nuevos), sin flakiness.

## Fase 2 — Auditoría de redundancia

Solo arranca cuando Fase 1 está en verde (red de seguridad antes de tocar
código compartido).

Candidatos a revisar (solapamiento de nombre/propósito, a confirmar leyendo
código, no asumir de antemano):

1. `core/graph.py` vs `core/graphquery.py` vs `core/refgraph.py` vs
   `core/orggraph.py` — 4 módulos "grafo"; confirmar responsabilidad de cada
   uno y buscar funciones clonadas.
2. `core/parser.py` vs `core/parser_generic.py` vs `core/parser_ts.py` —
   confirmar que el split es por lenguaje/capacidad y no hay lógica
   duplicada entre ellos.
3. `rag/scorer.py` vs `core/metrics.py` — ambos "puntúan" algo; confirmar que
   no se solapan en responsabilidad.

Para cada hallazgo real de redundancia: documentar módulo+símbolo duplicado,
decidir cuál es la versión a quedarse, y si el fix es seguro dentro de este
hito (test de Fase 1 lo cubre) aplicarlo; si no, dejarlo anotado en PLAN.md
para hito futuro en vez de forzarlo.

**Hecho cuando:** los 3 grupos revisados, hallazgos documentados, duplicados
seguros eliminados con tests en verde.

## PLAN.md

Insertar milestone `M2.5 — Hardening` entre M2 y M3 en el kanban, con:
- Nota de pausa explícita de M2 (Codex smoke test + mini-bench quedan
  pendientes, se retoman al cerrar M2.5).
- Checklist de los 8 archivos de Fase 1.
- Checklist de los 3 grupos de Fase 2.
- Actualizar "Última actualización" e hito activo.

## Fuera de alcance (explícito)

- No se tocan `rag/agent/*`, `rag/cli/*`, `rag/llm/*`, `plugins/*`,
  `meter/*`, `tui/*` en este hito.
- No se añade tooling de coverage (`pytest-cov`, umbrales de CI) — no lo pidió
  el usuario; YAGNI hasta que se pida.
- No se refactoriza fuera de lo que la Fase 2 encuentre como duplicado real.
