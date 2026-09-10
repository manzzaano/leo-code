# leo-mcp

**Servidor MCP que le da a tu agente de código un grafo estructural con prueba, en vez de dejarlo adivinar leyendo archivos.**

`leo-mcp` es el motor KC-RAG de este repo expuesto como servidor MCP (stdio) para
Claude Code, opencode, Cursor o cualquier cliente MCP. Dos tools:

- **`get_context`** — subgrafo del AST relevante a tu pregunta, cuerpos ya incluidos, comprimido. Sustituye a `read`/`grep`/`glob` para entender código.
- **`graph`** — consulta determinista al grafo real (`where` / `who_calls` / `impact` / `trace` / `guard`), citada `archivo:línea`, **cero tokens de LLM, cero alucinación**.

> El motor también tiene un agente TUI (`leo-code`) construido encima, como
> producto aparte — no se publica en este repo, que se queda enfocado 100% en
> `leo-mcp`.

---

## La garantía: corrección estructural con prueba, no estimada

`graph` no adivina la estructura del código — recorre el grafo real (AST) y cada
respuesta viene citada `archivo:línea`. Eso se verifica formalmente, no se
promete: `benchmark/audit_formal.py` re-deriva el grafo con parsers **que no son
los de leo** (el `ast` de Python, el compilador `tsc` de TypeScript) y compara
arista a arista. Corre gateado en CI (`.github/workflows/audit.yml`) — una
regresión no mergea.

Última corrida verde en CI ([`leo-code formal audit`](https://github.com/manzzaano/leo-code/actions/workflows/audit.yml), 2026-09-10, tras reestructurar el repo a solo motor+MCP, `FORMAL: 5/5 → IRREFUTABLE`):

| Check | Repos/escala | Resultado real medido |
|---|---|---|
| (a) Grafo Python vs `ast` | leo-code + 3 repos externos (~100.400 símbolos, ~480.200 aristas) | **100,000% precisión · 100,000% recall** (0 falsas, 0 perdidas) |
| (a-ts) Grafo TS/JS vs `tsc` | repo del compilador TypeScript (36.739 símbolos) | **99,950% precisión · 99,926% recall** (31 falsas / 46 perdidas sobre 62,2k aristas) |
| (b) Cobertura del guardián vs `coverage.py` | 113 funciones ejecutadas | **0 falsos** en ambas direcciones |
| (c) Blast radius vs mutation testing real | `compress` (19 tests fallaron, 107 predichos) · `classify_task` (11 fallaron, 106 predichos) | Todos los fallos **⊆** lo predicho |
| (d) SLA a escala | 271.493 símbolos indexados | query peor caso **1,98ms** (<50ms) · guardián **13ms** (<2s) |

El único check que no da 100,000% exacto es el de TS/JS (~99,93-99,95%) — se
deja el número real en vez de redondear para arriba; el resto de la garantía
formal (Python, guardián, blast radius, SLA) sí es 100%/0-falsos medido.
Reproducible: `python benchmark/audit_formal.py <repos>`.

## Números medidos (validación 3×, config final)

La tabla de criterio de éxito, medida y cerrada el 2026-07-14 (ver `docs/PLAN.md`
para el historial completo de falsaciones que llevó a esta config):

| Métrica | Umbral | Resultado medido |
|---|---|---|
| Corrección estructural (`graph`: impact/trace/guard/who_calls) | 100% precisión+recall vs oráculos, gateado en CI | ✅ probado (`audit_formal.py`) |
| Ahorro POR consulta (`get_context` vs leer los archivos que cubre) | 80–97% | ✅ probado (`token_efficiency.py`) |
| Calidad de respuesta (juez LLM, n=3) | agente con MCP ≥ agente sin MCP | ✅ +0,18 (5,00 vs 4,82) |
| Velocidad | duración ≤ +10% vs sin MCP | ✅ −14,2% |
| Sobrecoste de tokens end-to-end | ≤ +10% mediana por tarea | ✅ +1,9% mediana · **−30,1% pooled** |

La promesa honesta no es "ahorra tokens en cada turno" — es: **el ahorro real es
por consulta y viene de las tareas pesadas (pooled −30%); en la mediana por
tarea es neutro; lo que no tiene vanilla es la corrección estructural
garantizada.** Seis configuraciones anteriores probaron y fallaron un objetivo de
"−40% end-to-end" antes de que esta fuera la conclusión — el detalle completo
está en `docs/PLAN.md`.

---

## Instalación

`leo-mcp` todavía no está publicado en PyPI (`packaging/leo-mcp/` existe pero no
se ha subido) — por ahora se instala clonando este repo:

```bash
git clone https://github.com/manzzaano/leo-code.git
cd leo-code
pip install -e .
```

Registrar en **Claude Code**:

```bash
claude mcp add leo-code -- python -m leo_code.server.mcp_server
```

o vía `.mcp.json` del proyecto (este repo ya trae uno de ejemplo):

```json
{
  "mcpServers": {
    "leo-code": {
      "command": "python",
      "args": ["-m", "leo_code.server.mcp_server"],
      "env": { "LEO_REPO": "." }
    }
  }
}
```

**opencode** — `opencode.json`:

```json
{
  "mcp": {
    "leo-code": {
      "type": "local",
      "command": ["python", "-m", "leo_code.server.mcp_server"],
      "enabled": true
    }
  }
}
```

Sin API key propia: `leo-mcp` no llama a ningún LLM — indexa tu repo localmente
(AST + embeddings opcionales) y responde con eso. El primer arranque indexa
(estructural: segundos incluso en repos grandes; embeddings semánticos se
calientan en background sin bloquear).

---

## Cómo funciona

```
Código fuente
    ↓ AST (tree-sitter + ast de Python)         core/parser.py
Cápsulas: funciones/clases/módulos con calls, called_by, file:line
    ↓ índice híbrido (Qdrant semántico + BM25 + exacto + scorer → RRF)
    ↓ compresión adaptativa por tipo de tarea    rag/compressor.py
Contexto estructural (~400–2000 tokens) → tu agente
```

`graph` corre sobre el mismo índice, sin pasar por ningún modelo:

```
where(symbol)     → dónde se define (todas las definiciones), citado
who_calls(symbol) → quién lo llama, citado archivo:línea
impact(symbol)    → qué se ROMPE si lo cambias (cierre transitivo de callers), citado
trace(src, dst)   → camino de llamadas A→B (cruza archivos y lenguajes), cada salto citado
guard(symbol)     → antes de editar: afectados con test vs sin test
```

Cruza el límite HTTP/RPC: un `fetch('/api/users')` en el frontend queda cosido
al `@app.get('/api/users')` del backend (`core/boundary.py`), así `trace` sigue
un dato entre servicios, no solo dentro de un archivo.

---

## Arquitectura (camino de `leo-mcp`)

```
leo_code/
├── engine.py             # motor: indexado persistente + retrieval híbrido (RRF) + compresión
├── filectx.py            # vista comprimida de un archivo (usada por el hook de Claude Code)
├── core/
│   ├── parser.py         # AST → cápsulas (ast de Python + tree-sitter multi-lenguaje)
│   ├── parser_generic.py # fallback regex para lenguajes sin parser dedicado
│   ├── graphquery.py     # cerebro determinista: where/who_calls/impact/trace, con prueba
│   ├── guardian.py       # guard: afectados con/sin test antes de editar
│   ├── boundary.py       # aristas cross-lenguaje (cose el límite HTTP/RPC)
│   └── cache.py, tokens.py, evidence.py, metrics.py…
├── rag/
│   ├── indexer/          # indexado incremental (build/sync)
│   ├── compressor.py     # compresión adaptativa por tipo de tarea
│   └── vector_store.py, bm25.py, scorer.py, classifier.py, encoder.py
└── server/
    └── mcp_server.py     # servidor MCP (stdio): get_context + graph
```

---

## Tests

```bash
pytest tests/ -q     # 135 tests
```

Cada módulo trackeado de `leo_code/` tiene al menos un test directo o por
subprocess (`core/*`, `engine.py`, `filectx.py`, `logging_config.py`,
`rag/{indexer,bm25,classifier,compressor,encoder,scorer,vector_store}`,
`server/*`) — el camino completo de `get_context`/`graph` incluido. Ver
`docs/PLAN.md` para el detalle de qué se prueba dónde.

---

## Estado del proyecto

En desarrollo activo, pre-v1. Instalación y smoke test verificados en **Claude
Code** y **opencode**; **Codex** pendiente. Ver `docs/PLAN.md` para el kanban
completo y las decisiones tomadas con su porqué — es la fuente de verdad del
proyecto, no este README.

