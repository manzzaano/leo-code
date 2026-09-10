# M2.5 — Hardening del núcleo leo-mcp: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cobertura de smoke test en los 8 módulos del núcleo leo-mcp que hoy no tienen ningún test directo, más una auditoría de código redundante en `core/`, dejando el producto listo para v1.

**Architecture:** No hay cambio arquitectónico. Fase 1 añade un archivo `tests/test_<modulo>.py` por módulo, siguiendo la convención ya usada en el repo (funciones pytest sueltas, sin clases, `tmp_path` para fixtures). Fase 2 es lectura + comparación de 3 grupos de módulos `core/` y, si hay duplicado real, un fix acotado cubierto por los tests existentes/nuevos.

**Tech Stack:** Python 3.12, pytest (ya configurado, 206 tests existentes en `tests/`), sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-09-10-mcp-core-hardening-design.md`

## Global Constraints

- Alcance SOLO núcleo leo-mcp: `engine.py`, `filectx.py`, `core/*`, `rag/{bm25,classifier,compressor,encoder,scorer,vector_store}.py`, `rag/indexer/*`, `server/*`. No tocar `rag/agent/*`, `rag/cli/*`, `rag/llm/*`, `plugins/*`, `meter/*`, `tui/*` (agente TUI, fuera del cierre según `docs/PLAN.md`).
- Nivel de test: **smoke**, no exhaustivo. 1-4 tests por módulo: import limpio + llamada con input típico + no explota + forma del resultado correcta.
- Convención de estilo: funciones pytest sueltas (sin clases), `tmp_path` para fixtures de archivos, docstring de 1 línea solo si el "por qué" no es obvio — igual que `tests/test_vector_store_lock.py` y `tests/test_incremental_index.py`.
- Cada módulo de Fase 1 ya tiene código de producción existente (no es feature nueva): salvo que la tarea diga explícitamente "bug encontrado", el ciclo es escribir test → correr → debe pasar en verde a la primera (test de caracterización, no TDD de feature nueva).
- No añadir `pytest-cov` ni umbrales de CI — no lo pidió el usuario (YAGNI).
- Todo el texto de tests, docstrings y mensajes de commit en español, consistente con el resto del repo.

---

## File Structure

Nuevos archivos (Fase 1, uno por módulo):
- `tests/test_engine.py` — `leo_code/engine.py`
- `tests/test_filectx.py` — `leo_code/filectx.py`
- `tests/test_cache.py` — `leo_code/core/cache.py`
- `tests/test_evidence.py` — `leo_code/core/evidence.py`
- `tests/test_tokens.py` — `leo_code/core/tokens.py`
- `tests/test_parser_generic.py` — `leo_code/core/parser_generic.py` (incluye fix de un bug real encontrado durante la redacción de este plan)
- `tests/test_benchmark_core.py` — `leo_code/core/benchmark.py` (nombre con sufijo `_core` para no chocar con el paquete top-level `benchmark/` del repo)
- `tests/test_orggraph.py` — `leo_code/core/orggraph.py`

Modificado (Fase 1, Task 3): `leo_code/core/cache.py` (fix de 3 writers que revientan sin Redis).
Modificado (Fase 1, Task 6): `leo_code/core/parser_generic.py:476-477` (fix del bug de `set` no indexable).

Modificado (Task 9): `docs/PLAN.md` (nuevo milestone M2.5 en el kanban).

Fase 2 no crea archivos nuevos por defecto — solo si se confirma duplicado real, en cuyo caso la tarea correspondiente lo dice explícitamente.

---

## Task 1: `engine.py` — smoke test de `compute_context`

**Files:**
- Create: `tests/test_engine.py`
- Test: el propio archivo de arriba

**Interfaces:**
- Consumes: `leo_code.engine._get_indexer() -> Indexer` (ya existe), `leo_code.engine.compute_context(repo: str, query: str, task_type_in: str = "auto", budget_tokens_in: int = 0, self_sufficient: bool = False) -> dict` con claves `context: str`, `tokens: int`, `task_type: str`, `capsules_total: int` (ya existe, `leo_code/engine.py:221`).
- Produces: nada consumido por tareas posteriores.

- [ ] **Step 1: Escribir el test**

```python
"""Smoke test: compute_context arma un subgrafo comprimido sin reventar."""

from leo_code.engine import _get_indexer, compute_context


def test_compute_context_finds_named_function(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python"])

    result = compute_context(str(tmp_path), "say_hello", task_type_in="code_query")

    assert "say_hello" in result["context"]
    assert result["capsules_total"] >= 1
    assert result["tokens"] > 0
    assert result["task_type"] == "code_query"


def test_compute_context_no_code_returns_documents(tmp_path):
    (tmp_path / "notas.md").write_text(
        "# Notas\nEste modulo explica la arquitectura general.\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python", "text"])

    result = compute_context(str(tmp_path), "arquitectura", task_type_in="no_code")

    assert result["task_type"] == "no_code"
    assert isinstance(result["context"], str)
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (código de producción ya existe; esto es test de caracterización, no TDD de feature nueva). Si falla, es un bug real — investigar antes de seguir, no ajustar el test para que pase artificialmente.

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine.py
git commit -m "test: smoke test de compute_context (engine.py, sin cobertura directa hasta ahora)"
```

---

## Task 2: `filectx.py` — smoke test del CLI de vista comprimida

**Files:**
- Create: `tests/test_filectx.py`

**Interfaces:**
- Consumes: `python -m leo_code.filectx <file> --repo <repo>` (CLI, `leo_code/filectx.py:17`) — invocado vía `subprocess`, no vía import (es un script standalone con `sys.exit`).
- Produces: nada.

- [ ] **Step 1: Escribir el test**

```python
"""Smoke test del CLI leo_code.filectx: vista comprimida de un archivo vía subprocess
(es un script standalone con sys.exit, no una función importable)."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_filectx(repo: Path, file: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "leo_code.filectx", file, "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8",
        cwd=REPO_ROOT,
    )


def test_filectx_prints_compressed_view(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    result = _run_filectx(tmp_path, "greet.py")

    assert result.returncode == 0, result.stderr
    assert "COMPRIMIDO" in result.stdout
    assert "say_hello" in result.stdout


def test_filectx_exit_3_when_file_not_indexed(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    result = _run_filectx(tmp_path, "no_existe.py")

    assert result.returncode == 3
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_filectx.py -v`
Expected: PASS. `filectx.py` hace `os.chdir(repo)` antes de importar `leo_code.engine`, así que `LEO_CACHE_DIR` relativo queda dentro de `tmp_path/cache` — no toca el `./cache` real del repo.

- [ ] **Step 3: Commit**

```bash
git add tests/test_filectx.py
git commit -m "test: smoke test del CLI filectx (swap del hook Claude Code)"
```

---

## Task 3: `core/cache.py` — smoke test + fix de bug real (writers revientan sin Redis)

Durante la redacción de este plan se confirmó un segundo bug real:
`cache_result`, `cache_subgraph` y `cache_ontology` acceden a `_client.setex`/
`_client.set` como argumento posicional ANTES de que `_safe_op` compruebe si
`_client` es `None` — Python evalúa `_client.setex` al construir la llamada,
así que revienta con `AttributeError: 'NoneType' object has no attribute
'setex'` en el caso normal sin Redis. Los getters (`get_cached_result`, etc.)
SÍ están bien: usan `... if _client else None`, que corto-circuita antes de
tocar `_client`. Solo no explota en producción porque
`engine._cache_context_result` envuelve la llamada en `try/except Exception`
— tapa el síntoma, no arregla la causa. Esta tarea sigue TDD rojo→verde real.

**Files:**
- Create: `tests/test_cache.py`
- Modify: `leo_code/core/cache.py` (funciones `cache_result`, `cache_subgraph`, `cache_ontology`)

**Interfaces:**
- Consumes: `leo_code.core.cache.is_available() -> bool`, `get_cached_result(query: str) -> dict | None`, `cache_result(query: str, result: dict, ttl: int = 60) -> None`, `cache_subgraph(entity_id: str, subgraph: dict, ttl: int = 300) -> None`, `cache_ontology(domain: str, ontology: dict) -> None`, `_is_circuit_open() -> bool`, `_record_failure() -> None`, `_record_success() -> None`, `CB_THRESHOLD: int` (todo ya existe, `leo_code/core/cache.py`).
- Produces: nada.

- [ ] **Step 1: Escribir los tests (incluye los que exponen el bug)**

```python
"""Smoke test: sin Redis disponible (_client=None, estado por defecto del módulo),
las operaciones de cache deben degradar a no-op en vez de reventar; el circuit
breaker abre tras N fallos consecutivos."""

from leo_code.core import cache


def test_writers_are_safe_noop_without_client():
    cache._client = None
    cache._failures = 0
    cache._last_failure = 0.0

    assert cache.is_available() is False
    cache.cache_result("una query", {"a": 1})       # no debe reventar
    cache.cache_subgraph("entidad-1", {"n": 1})      # no debe reventar
    cache.cache_ontology("dominio-x", {"o": 1})      # no debe reventar
    assert cache.get_cached_result("una query") is None


def test_circuit_breaker_opens_after_threshold_and_recovers():
    cache._client = object()  # simula cliente presente, sin conexion real
    cache._failures = 0
    cache._last_failure = 0.0

    for _ in range(cache.CB_THRESHOLD):
        cache._record_failure()
    assert cache._is_circuit_open() is True

    cache._record_success()
    assert cache._is_circuit_open() is False

    cache._client = None  # deja el modulo limpio para otros tests
```

- [ ] **Step 2: Correr los tests — confirmar que el de writers falla**

Run: `pytest tests/test_cache.py -v`
Expected: `test_circuit_breaker_opens_after_threshold_and_recovers` PASA.
`test_writers_are_safe_noop_without_client` **FALLA** con
`AttributeError: 'NoneType' object has no attribute 'setex'` en la línea de
`cache.cache_result(...)`.

- [ ] **Step 3: Fix mínimo — guard `if not _client: return` en cada writer**

En `leo_code/core/cache.py`, las 3 funciones quedan:

```python
def cache_result(query: str, result: dict, ttl: int = 60):
    if not _client:
        return
    _safe_op(_client.setex, _query_key(query), ttl, json.dumps(result, ensure_ascii=False))


def cache_subgraph(entity_id: str, subgraph: dict, ttl: int = 300):
    if not _client:
        return
    _safe_op(_client.setex, _subgraph_key(entity_id), ttl, json.dumps(subgraph, ensure_ascii=False))


def cache_ontology(domain: str, ontology: dict):
    if not _client:
        return
    _safe_op(_client.set, f"ontology:{domain}", json.dumps(ontology, ensure_ascii=False))
```

- [ ] **Step 4: Correr los tests otra vez — deben pasar los 2**

Run: `pytest tests/test_cache.py -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add tests/test_cache.py leo_code/core/cache.py
git commit -m "fix(cache): writers reventaban sin Redis (_client.setex sobre None antes del guard)

cache_result/cache_subgraph/cache_ontology evaluaban _client.setex como
argumento posicional antes de que _safe_op comprobara _client is None.
Enmascarado en produccion por el try/except de engine._cache_context_result.
Cubierto por tests/test_cache.py::test_writers_are_safe_noop_without_client."
```

---

## Task 4: `core/evidence.py` — smoke test de extracción y verificación de evidencia

**Files:**
- Create: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `leo_code.core.evidence.extract_evidence(respuesta: str, nodes: list[dict]) -> tuple[list[dict], list[str]]`, `verify_grounding(evidence: list[dict], nodes: list[dict]) -> dict` (ya existen, `leo_code/core/evidence.py`).
- Produces: nada.

- [ ] **Step 1: Escribir el test**

```python
"""Smoke test: extracción determinista de evidencia (sin LLM) encuentra nodos
mencionados en el texto y verify_grounding puntúa contra el subgrafo."""

from leo_code.core.evidence import extract_evidence, verify_grounding


def test_extract_evidence_finds_mentioned_node():
    nodes = [{"id": "n1", "name": "build_report", "type": "function"}]

    evidence, inferencias = extract_evidence(
        "La funcion build_report arma el reporte.", nodes
    )

    assert evidence[0]["node_id"] == "n1"
    assert inferencias == []


def test_extract_evidence_lists_unmentioned_as_inferencia():
    nodes = [{"id": "n1", "name": "build_report", "type": "function"}]

    evidence, inferencias = extract_evidence("Texto que no menciona nada relevante.", nodes)

    assert evidence == []
    assert len(inferencias) == 1


def test_verify_grounding_scores_partial_match():
    nodes = [{"id": "n1", "name": "a"}, {"id": "n2", "name": "b"}]
    evidence = [{"node_id": "n1", "relacion": "x", "valor": "a"}]

    result = verify_grounding(evidence, nodes)

    assert result["verified_claims"] == 1
    assert result["total_entities_in_context"] == 2
    assert result["score"] == 0.5
    assert result["low_confidence"] is True
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_evidence.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_evidence.py
git commit -m "test: smoke test de core/evidence.py (extraccion y grounding)"
```

---

## Task 5: `core/tokens.py` — smoke test del conteo de tokens

**Files:**
- Create: `tests/test_tokens.py`

**Interfaces:**
- Consumes: `leo_code.core.tokens.count_tokens(text: str, model: str = "cl100k_base") -> int` (ya existe, `leo_code/core/tokens.py:19`).
- Produces: nada.

- [ ] **Step 1: Escribir el test**

```python
"""Smoke test: count_tokens no revienta con tiktoken presente o ausente
(fallback heuristico ~4 chars/token), y es monotono con la longitud del texto."""

from leo_code.core.tokens import count_tokens


def test_empty_text_is_zero_tokens():
    assert count_tokens("") == 0


def test_nonempty_text_has_positive_tokens():
    assert count_tokens("hola mundo") > 0


def test_longer_text_has_more_tokens():
    assert count_tokens("palabra " * 200) > count_tokens("palabra " * 5)
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS (con o sin `tiktoken` instalado — el fallback heurístico cubre ambos casos).

- [ ] **Step 3: Commit**

```bash
git add tests/test_tokens.py
git commit -m "test: smoke test de core/tokens.py (conteo con y sin tiktoken)"
```

---

## Task 6: `core/parser_generic.py` — smoke test + fix de bug real (`set` no indexable en CSS)

Durante la redacción de este plan se confirmó un bug real: `_parse_css` hace
`set(selectors)[:30]` y `set(colors)[:20]` — un `set` no soporta slicing, así
que **toda** llamada a `extract_html_css` con `language="css"` revienta con
`TypeError: 'set' object is not subscriptable`. Esta tarea sí sigue TDD
rojo→verde real (a diferencia de las demás, que son caracterización).

**Files:**
- Create: `tests/test_parser_generic.py`
- Modify: `leo_code/core/parser_generic.py:476-477`

**Interfaces:**
- Consumes: `leo_code.core.parser_generic.extract_generic(content: str, file_path: str, language: str) -> list[Capsule]`, `extract_html_css(content: str, file_path: str, language: str) -> list[Capsule]` (ya existen, `leo_code/core/parser_generic.py:151` y `:398`). `Capsule` viene de `leo_code.core.parser` (ya tiene tests propios).
- Produces: nada.

- [ ] **Step 1: Escribir los tests (incluye el que expone el bug)**

```python
"""Smoke test del parser generico multi-lenguaje (regex-based, sin tree-sitter)."""

from leo_code.core.parser_generic import extract_generic, extract_html_css


def test_extract_generic_javascript_function():
    caps = extract_generic(
        "function greet(name) {\n  return name;\n}\n", "greet.js", "javascript"
    )
    assert "greet" in {c.name for c in caps}


def test_extract_generic_unknown_language_uses_heuristic_fallback():
    caps = extract_generic("def greet():\n    return 1\n", "greet.mystery", "cobol")
    assert isinstance(caps, list)  # lenguaje sin patterns: no debe reventar


def test_extract_html_css_html_collects_tags_and_classes():
    caps = extract_html_css(
        '<html><body class="main"><h1>Hola</h1></body></html>', "index.html", "html"
    )
    assert caps[0].type == "document"
    assert "h1" in caps[0].properties["tags"]
    assert "main" in caps[0].properties["css_classes"]


def test_extract_html_css_css_collects_selectors():
    caps = extract_html_css(".btn { color: red; }", "style.css", "css")
    assert ".btn" in caps[0].properties["selectors"]
```

- [ ] **Step 2: Correr los tests — confirmar que el de CSS falla**

Run: `pytest tests/test_parser_generic.py -v`
Expected: 3 PASS, `test_extract_html_css_css_collects_selectors` **FAILS** con
`TypeError: 'set' object is not subscriptable` (dentro de `_parse_css`).

- [ ] **Step 3: Fix mínimo — `set` no es indexable, `sorted()` sí y de paso da orden estable**

En `leo_code/core/parser_generic.py`, dentro de `_parse_css` (líneas 476-477):

```python
            "selectors": ", ".join(sorted(set(selectors))[:30]),
            "colors": ", ".join(sorted(set(colors))[:20]),
```

- [ ] **Step 4: Correr los tests otra vez — deben pasar los 4**

Run: `pytest tests/test_parser_generic.py -v`
Expected: PASS (4/4).

- [ ] **Step 5: Commit**

```bash
git add tests/test_parser_generic.py leo_code/core/parser_generic.py
git commit -m "fix(parser_generic): set no es indexable en _parse_css, rompia extract_html_css con CSS

Toda llamada con language=css reventaba con TypeError. Cubierto por
tests/test_parser_generic.py::test_extract_html_css_css_collects_selectors."
```

---

## Task 7: `core/benchmark.py` — smoke test de scoring y reporte

**Files:**
- Create: `tests/test_benchmark_core.py`

**Interfaces:**
- Consumes: `leo_code.core.benchmark.score_answer(generated: str, criterios: list[str]) -> dict`, `llm_judge(generated: str, criterios: list[str], llm_fn) -> bool`, `benchmark_queries(queries: list[dict], run_query_fn, llm_fn=None) -> list[dict]`, `print_benchmark_report(results: list[dict], baseline_tokens: int = 0) -> None` (ya existen, `leo_code/core/benchmark.py`).
- Produces: nada.

- [ ] **Step 1: Escribir el test**

```python
"""Smoke test: scoring de respuestas contra criterios, judge por LLM inyectado
(sin llamar a ningun LLM real) y el pipeline completo de benchmark_queries."""

from leo_code.core.benchmark import (
    benchmark_queries, llm_judge, print_benchmark_report, score_answer,
)


def test_score_answer_counts_hits_and_misses():
    result = score_answer("La funcion usa cache y grafo.", ["cache", "grafo", "redis"])

    assert result["acertados"] == 2
    assert result["fallados"] == ["redis"]
    assert result["score"] == 0.67


def test_llm_judge_uses_injected_fn_not_a_real_llm():
    assert llm_judge("texto", ["a"], llm_fn=lambda prompt: "SI") is True
    assert llm_judge("texto", ["a"], llm_fn=lambda prompt: "NO") is False


def test_llm_judge_swallows_exceptions_from_llm_fn():
    def _boom(prompt):
        raise RuntimeError("llm caido")

    assert llm_judge("texto", ["a"], llm_fn=_boom) is False


def test_benchmark_queries_runs_end_to_end_with_fake_backends():
    queries = [{"query": "que hace X?", "criterios": ["cache"]}]

    def _run_query_fn(q):
        return {"respuesta": "X usa cache internamente.", "_meta": {"total_tokens": 42}}

    results = benchmark_queries(queries, _run_query_fn, llm_fn=lambda p: "SI")

    assert results[0]["criteria_score"] == 1.0
    assert results[0]["llm_correct"] is True

    print_benchmark_report(results)  # no debe reventar (smoke del reporte impreso)
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_benchmark_core.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_benchmark_core.py
git commit -m "test: smoke test de core/benchmark.py (scoring, judge inyectado, reporte)"
```

---

## Task 8: `core/orggraph.py` — ejecutar el self-check ya incluido en el módulo

**Files:**
- Create: `tests/test_orggraph.py`

**Interfaces:**
- Consumes: `leo_code.core.orggraph._demo() -> None` — self-check ya escrito en el propio módulo (`leo_code/core/orggraph.py:81`, dos repos sintéticos frontend/backend unidos por `link_http_edges`, con sus propios `assert`).
- Produces: nada.

- [ ] **Step 1: Escribir el test**

```python
"""orggraph.py ya trae su propio self-check (_demo, con asserts) para validar
el trace cross-repo/cross-lenguaje sin red ni repos reales. Este test solo lo
engancha a pytest para que corra en CI en vez de depender de invocacion manual."""

from leo_code.core.orggraph import _demo


def test_orggraph_self_check_runs_clean(capsys):
    _demo()  # revienta con AssertionError si el trace cross-repo se rompe

    out = capsys.readouterr().out
    assert "self-check OK" in out
```

- [ ] **Step 2: Correr el test**

Run: `pytest tests/test_orggraph.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_orggraph.py
git commit -m "test: enganchar el self-check ya existente de orggraph.py a pytest"
```

---

## Task 9: Suite completa en verde + cierre de Fase 1

**Files:** ninguno nuevo — solo verificación.

**Interfaces:** N/A.

- [ ] **Step 1: Correr la suite completa**

Run: `pytest tests/ -q`
Expected: `214 passed` (206 existentes + 8 archivos nuevos de Fase 1; el conteo exacto de tests nuevos puede variar según cuántas funciones de test terminen quedando por archivo — lo que importa es 0 failed, 0 error).

- [ ] **Step 2: Si algo falla, parar aquí**

No seguir a Fase 2 con la suite en rojo — es la red de seguridad para los cambios de dedup.

---

## Task 10: Fase 2 — auditoría de redundancia, grupo grafo (`core/graph.py` vs `graphquery.py` vs `refgraph.py` vs `orggraph.py`)

**Files:**
- Modify (posible, según hallazgo): alguno de los 4 módulos.
- Modify: `docs/PLAN.md` (sección de notas de sesión, documentar hallazgo aunque no se toque código).

**Interfaces:** N/A — tarea de lectura y comparación.

- [ ] **Step 1: Leer las funciones públicas de los 4 módulos**

```bash
grep -n "^def \|^class " leo_code/core/graph.py leo_code/core/graphquery.py leo_code/core/refgraph.py leo_code/core/orggraph.py
```

- [ ] **Step 2: Para cada símbolo con nombre igual o muy similar en 2+ archivos, leer ambas implementaciones completas y decidir**

Usar `codegraph_node` o `Read` sobre cada símbolo señalado en el Step 1. Para
cada coincidencia, clasificar en una de tres cajas:
- **Mismo nombre, responsabilidad distinta** (ej. `where` en `graphquery.py`
  como método de consulta vs. algo homónimo en otro módulo con otro
  propósito) → no es redundancia, anotar y seguir.
- **Duplicado real** (misma lógica copiada) → unificar: el módulo que ya
  tiene tests existentes (ver Fase 1 / suite de 206) gana, el otro pasa a
  importar de ahí. Solo aplicar si la suite completa (Task 9) sigue en verde
  después del cambio.
- **Solapamiento parcial pero con razón arquitectónica** (ej. `orggraph.py`
  reutiliza `GraphQuery`/`link_http_edges` de los otros a propósito, para
  multi-repo) → no es redundancia, es composición; anotar por qué.

- [ ] **Step 3: Si hay fix, aplicarlo y correr la suite**

Run: `pytest tests/ -q`
Expected: mismo conteo que Task 9, 0 failed.

- [ ] **Step 4: Documentar el hallazgo en PLAN.md** (aunque no haya cambio de código)

Añadir bajo "Notas de sesión" de `docs/PLAN.md`, con fecha, 2-4 líneas: qué se
comparó, si había duplicado real o no, y qué se hizo.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(dedup): auditoria grupo grafo (graph/graphquery/refgraph/orggraph) — ver PLAN.md"
```

(Si Step 3 no tocó código, el commit solo lleva el cambio de `docs/PLAN.md`.)

---

## Task 11: Fase 2 — auditoría de redundancia, grupo parser (`core/parser.py` vs `parser_generic.py` vs `parser_ts.py`)

**Files:**
- Modify (posible, según hallazgo): alguno de los 3 módulos.
- Modify: `docs/PLAN.md`.

**Interfaces:** N/A — tarea de lectura y comparación.

- [ ] **Step 1: Leer las funciones públicas de los 3 módulos**

```bash
grep -n "^def \|^class " leo_code/core/parser.py leo_code/core/parser_generic.py leo_code/core/parser_ts.py
```

- [ ] **Step 2: Confirmar la frontera esperada y buscar excepciones**

Frontera esperada (a verificar, no asumir): `parser.py` = Python vía `ast` +
`Capsule`/`_make_id` compartidos; `parser_ts.py` = lenguajes con gramática
tree-sitter real; `parser_generic.py` = fallback regex para el resto. Si algún
símbolo de `parser_generic.py` reimplementa algo que `parser_ts.py` ya cubre
para el MISMO lenguaje (ej. ambos con patterns para `typescript`), es
redundancia real — decidir cuál gana igual que en Task 10 Step 2.

- [ ] **Step 3: Si hay fix, aplicarlo y correr la suite**

Run: `pytest tests/ -q`
Expected: 0 failed.

- [ ] **Step 4: Documentar el hallazgo en PLAN.md**

Igual formato que Task 10 Step 4.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(dedup): auditoria grupo parser (parser/parser_generic/parser_ts) — ver PLAN.md"
```

---

## Task 12: Fase 2 — auditoría de redundancia, `rag/scorer.py` vs `core/metrics.py`

**Files:**
- Modify (posible, según hallazgo): alguno de los 2 módulos.
- Modify: `docs/PLAN.md`.

**Interfaces:** N/A — tarea de lectura y comparación.

- [ ] **Step 1: Leer las funciones públicas de ambos módulos**

```bash
grep -n "^def \|^class " leo_code/rag/scorer.py leo_code/core/metrics.py
```

- [ ] **Step 2: Comparar responsabilidad**

`rag/scorer.py` puntúa cápsulas candidatas dentro del retrieval (`score_capsules`,
usado por `engine.compute_context`). `core/metrics.py` es de otro dominio
(confirmar leyendo el archivo — no asumir qué mide). Si ambos calculan la
misma métrica (ej. algún PageRank/TF-IDF duplicado) es redundancia real;
si no, documentar que la similitud es solo de nombre.

- [ ] **Step 3: Si hay fix, aplicarlo y correr la suite**

Run: `pytest tests/ -q`
Expected: 0 failed.

- [ ] **Step 4: Documentar el hallazgo en PLAN.md**

Igual formato que Task 10 Step 4.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(dedup): auditoria scorer vs metrics — ver PLAN.md"
```

---

## Task 13: Cerrar M2.5 en PLAN.md

**Files:**
- Modify: `docs/PLAN.md`

**Interfaces:** N/A.

- [ ] **Step 1: Insertar el milestone M2.5 en el kanban**

En `docs/PLAN.md`, entre la sección `### 🔵 M2 — Multi-harness` (que termina en
su línea `**Done cuando:** ...`) y `### ⚪ M3 — Empaquetado`, insertar:

```markdown
### ✅ M2.5 — Hardening núcleo leo-mcp (2026-09-10)
- [x] 8 módulos sin test directo cubiertos con smoke tests: `engine.py`,
  `filectx.py`, `core/cache.py`, `core/evidence.py`, `core/tokens.py`,
  `core/parser_generic.py`, `core/benchmark.py`, `core/orggraph.py`.
- [x] 2 bugs reales encontrados y arreglados: `core/cache.py` (writers
  `cache_result`/`cache_subgraph`/`cache_ontology` reventaban con
  `AttributeError` sin Redis, tapado por un `try/except` en `engine.py`) y
  `core/parser_generic.py` `_parse_css` (`set(...)[:30]` no indexable —
  `extract_html_css` con CSS reventaba siempre). Fix + test de regresión en
  ambos.
- [x] Auditoría de redundancia: grupo grafo (graph/graphquery/refgraph/orggraph),
  grupo parser (parser/parser_generic/parser_ts), scorer vs metrics — ver
  notas de sesión de esta fecha para el detalle de cada hallazgo.
- **Resultado:** suite en verde (206 + nuevos), núcleo leo-mcp con cobertura
  directa en el camino crítico. M2 (Codex smoke test + mini-bench) se retoma
  a continuación.
- **Done cuando:** Fase 1 + Fase 2 completas → **CERRADO 2026-09-10**
```

- [ ] **Step 2: Actualizar cabecera del PLAN**

Cambiar la línea 7 de `**Última actualización:** ... · **Hito activo: M2 —
Multi-harness**` a la fecha/hora real de cierre de este plan, con
`**Hito activo: M2 — Multi-harness (retomado tras M2.5)**`.

- [ ] **Step 3: Commit**

```bash
git add docs/PLAN.md
git commit -m "docs(plan): cierre M2.5 hardening, M2 se retoma"
```

---

## Self-Review

**Cobertura del spec:** Fase 1 (8 módulos) → Tasks 1-8. Suite en verde antes
de Fase 2 → Task 9. Fase 2 (3 grupos) → Tasks 10-12. PLAN.md → Task 13
(inserción) + Tasks 10-12 Step 4 (notas incrementales). Sin brechas frente al
spec `2026-09-10-mcp-core-hardening-design.md`.

**Placeholders:** ninguno — cada task trae código de test completo o comandos
`grep`/`git` exactos; las tareas de Fase 2 son investigación genuina (el
resultado no se puede predeterminar) pero cada paso especifica qué leer, qué
comando correr y qué decidir, no un "TBD".

**Consistencia de tipos/nombres:** `compute_context`, `extract_evidence`,
`verify_grounding`, `count_tokens`, `extract_generic`, `extract_html_css`,
`score_answer`, `llm_judge`, `benchmark_queries`, `print_benchmark_report`,
`_demo` — todas las firmas usadas en los tests fueron leídas directamente del
código fuente citado en cada Task, no inventadas.
