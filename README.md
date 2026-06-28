# 🧠 leo-code

**Un agente de código que no alucina sobre tu código y no se ahoga en repos grandes.**

leo-code construye un grafo determinista del AST de tu codebase y lo usa de dos formas:
te da el **subgrafo comprimido** que tu modelo necesita (en vez del archivo entero) y
responde las preguntas **estructurales** —qué llama a qué, qué se rompe, cómo fluye un
dato de A a B— con **prueba citable y cero tokens de LLM**.

Se entrega como **dos productos open source sobre un motor compartido**:

| Producto | Qué es | Para quién |
|----------|--------|------------|
| **`leo-code`** | El agente de código, con el motor integrado por dentro | Lo usas como tu agente (tipo Claude Code / opencode) |
| **`leo-mcp`** | El motor expuesto como servidor MCP | Lo enchufas a tu agente favorito y aprovechas el ahorro de tokens |

Ambos dependen de **`leo-code-core`** (el motor: indexado + retrieval + compresión +
cerebro determinista), que no arrastra ni el agente ni el servidor HTTP.

---

## Por qué es distinto

El cuello de botella de los agentes de código no es el modelo: es el **contexto**.

- **Leer archivos enteros gasta tokens en ruido.** El motor extrae funciones/clases
  completas con sus dependencias directas del AST y devuelve solo el subgrafo
  relevante, comprimido según la tarea → **~80–97% menos tokens** sin perder la señal.
- **Los LLM alucinan sobre la estructura.** Para "quién llama a esto" o "qué se rompe si
  lo cambio", leo no adivina: recorre el grafo real y responde con **prueba citable
  (`archivo:línea` + arista)**, gastando **cero tokens de LLM**.
- **Los repos grandes revientan el context window.** Un monorepo de 5M LOC son ~12M
  tokens (58× una ventana de 200k). leo responde cualquier símbolo en <2k tokens.

### Números verificados

| Métrica | Valor | Cómo |
|---------|-------|------|
| Reducción de tokens (vs leer el archivo) | **80–97%** | `benchmark/token_efficiency.py`, `_scale.py` |
| Recall del símbolo objetivo | **100%** | guard determinista, sin LLM |
| Escala | **5M+ LOC, 7 repos, multi-lenguaje** (Python+TS+JS) en un grafo | `core/orggraph.py` |
| Preguntas estructurales | trace/impact/who_calls/where en **0–16ms, con prueba** | `core/graphquery.py` |

---

## El cerebro determinista

```
trace(src, dst)   → camino de llamadas A→B (cruza archivos, repos y lenguajes), cada salto citado
impact(symbol)    → qué se ROMPE si lo cambias (cierre transitivo de callers), citado
who_calls(symbol) → quién lo llama, citado archivo:línea
where(symbol)     → dónde se define (todas las definiciones), citado
```

Cruza el límite **HTTP/RPC**: un `fetch('/api/users')` en React queda cosido al
`@app.get('/api/users')` de FastAPI (`core/boundary.py`), así `trace` sigue un dato
desde el botón hasta la columna de DB a través de varios servicios.

---

## Instalación

```bash
git clone https://github.com/manzzaano/leo-code.git
cd leo-code
pip install -e .

# Variables de entorno según proveedor del agente
export DEEPSEEK_API_KEY=sk-...      # o ANTHROPIC_API_KEY / OPENAI_API_KEY
```

## Uso

### Producto 1 — el agente

```bash
leo-code            # CLI del agente (usa el motor: inyecta contexto + tools deterministas)
```

#### Modelos / proveedores

leo es multi-proveedor; el modelo se indica como `proveedor/modelo`.

**Claude con tu suscripción (Claude Pro/Max — sin pagar por token)**, igual que Claude Code:

```bash
pip install "anthropic>=0.69"
ant auth login                                 # inicia sesión con tu cuenta de Claude (OAuth)
leo-code --model anthropic/claude-opus-4-8     # el más capaz (1M de contexto)
```

leo detecta el token OAuth de la suscripción (de `ant auth login` o `ANTHROPIC_AUTH_TOKEN`)
y autentica con Bearer + el header `oauth-2025-04-20`. **No pongas `ANTHROPIC_API_KEY`** si
quieres usar la suscripción.

**Claude con API key de pago** (alternativa): `export ANTHROPIC_API_KEY=sk-ant-...` y el
mismo `--model`. Si la key está puesta, manda sobre la suscripción.

El provider adapta la petición al modelo (omite `temperature` donde la rechazan, mapea el
esfuerzo a `output_config.effort`, gestiona refusals). Otros: `deepseek/…`, `openai/…`,
`google/…`, `groq/…`, `mistral/…`, `ollama/…`, `bedrock/…`.

### Producto 2 — el motor vía MCP

Regístralo en tu cliente MCP (Claude Code, opencode, Cursor…):

```json
{
  "mcpServers": {
    "leo-code": { "command": "python", "args": ["-m", "leo_code.server.mcp_server"] }
  }
}
```

Tools que expone: `get_context` (subgrafo comprimido) + `trace` / `impact` /
`who_calls` / `where` (deterministas, con prueba, cero LLM).

### El motor programáticamente

```python
from leo_code import engine
import asyncio

asyncio.run(engine._ensure_indexed("./mi-repo"))
ctx = engine.compute_context("./mi-repo", "¿qué hace process_payment?")["context"]
```

---

## Arquitectura

```
leo_code/
├── engine.py            # MOTOR: indexado persistente + retrieval híbrido (RRF) + compresión   ← leo-code-core
├── core/                # núcleo compartido (sin FastAPI ni agente)
│   ├── parser.py        # AST → cápsulas (Python ast + tree-sitter multi-lenguaje)
│   ├── graphquery.py    # cerebro determinista: where/who_calls/impact/trace, con prueba
│   ├── boundary.py      # aristas cross-lenguaje (cose el límite HTTP/RPC)
│   ├── orggraph.py      # un grafo que une N repos y varios lenguajes
│   ├── compressor.py    # compresión adaptativa por tipo de tarea
│   └── tokens, cache, metrics, graph…
├── rag/                 # retrieval (encoder, vector_store, bm25, scorer, classifier, indexer)
│   └── agent/           # PRODUCTO 1: el agente (loop + tools, con el motor integrado)
└── server/
    ├── mcp_server.py    # PRODUCTO 2: servidor MCP (stdio) sobre el motor
    └── server.py        # servidor HTTP opcional (wrapper fino sobre engine)
```

### Cómo funciona el motor

```
Código fuente
    ↓ AST (tree-sitter + Python ast)          parser.py
Cápsulas: funciones/clases/módulos con calls, called_by, file:line
    ↓ índice híbrido (Qdrant semántico + BM25 + exacto + scorer → RRF)
    ↓ compresión adaptativa por tarea          compressor.py
Contexto estructural (~400–2000 tokens) → al modelo
```

---

## Tests y benchmarks

```bash
pytest                                  # suite (119 tests)
python benchmark/token_efficiency.py    # reducción de tokens + recall (determinista)
python benchmark/retrieval_bench.py     # recall estructural (guard CI)
python benchmark/mcp_client_bench.py    # producto 2 end-to-end vía cliente MCP real
```

---

## Licencia

MIT.
