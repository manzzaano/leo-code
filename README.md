# 🧠 leo-code

**La primera inteligencia de código DEMOSTRADA, no estimada.**

Todos los agentes prometen "entender tu código". leo-code es el único que lo **prueba**:

> Cada respuesta estructural —quién llama a qué, qué se rompe, cómo fluye un dato de
> A a B— sale de un grafo verificado al **100% de precisión Y recall contra oráculos
> independientes** (el `ast` de Python y el **compilador de TypeScript**) sobre repos
> reales de **~6 millones de líneas**, con **cero tokens de LLM** y cada resultado
> citado `archivo:línea`. La verificación corre **gateada en CI**: si una regresión
> rompe la garantía, el commit no mergea.

Eso es una categoría nueva: **inteligencia de código con prueba formal**
(*proof-carrying code intelligence*). GPT-5, Claude, Copilot, Cursor y opencode
*estiman* la estructura de tu repo; leo la **demuestra** — y cuando alucinar no es
una opción (¿puedo borrar esta función? ¿qué rompe este cambio?), esa diferencia
es todo el producto.

Se entrega como **dos productos open source sobre un motor compartido**:

| Producto | Qué es | Para quién |
|----------|--------|------------|
| **`leo-code`** | El agente de código con TUI cockpit (chat + grafo en vivo + medidor de ahorro) | Lo usas como tu agente (tipo Claude Code / opencode) |
| **`leo-mcp`** | El motor expuesto como servidor MCP (6 tools) | Lo enchufas a Claude Code / opencode / Cursor y tu agente deja de alucinar estructura |

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

### La garantía (auditoría formal, no marketing)

`python benchmark/audit_formal.py` re-deriva el grafo con **parsers que no son los de
leo** y compara arista a arista. Exit 0 solo al 100% en TODO; corre en CI en cada push:

| Check | Resultado medido | Oráculo independiente |
|-------|------------------|----------------------|
| (a) Grafo Python SOUND + COMPLETE | **100% precisión · 100% recall** (~277k símbolos, 8 repos: Django, sympy, cpython…) | módulo `ast` de Python |
| (a-ts) Grafo TS/JS SOUND + COMPLETE | **100% · 100%** (80.291 aristas, repo del compilador TS) | compilador `tsc` (Node) |
| (b) Cobertura del guardián | **0 falsos en ambas direcciones** | `coverage.py` ejecutando los tests reales |
| (c) Blast radius completo | tests que fallan al romper X **⊆** lo predicho | mutation testing real |
| (d) SLA a ~6M LOC (499k símbolos) | query peor caso **3,3ms** (<50ms) · guardián **1,1s** (<2s) | reloj |
| (e) Reproducible y gateado | exit 0 solo si TODO pasa | GitHub Actions |

### Números de eficiencia

| Métrica | Valor | Cómo |
|---------|-------|------|
| Reducción de tokens (vs leer el archivo) | **80–97%** | `benchmark/token_efficiency.py`, `_scale.py` |
| Recall del símbolo objetivo | **100%** | guard determinista, sin LLM |
| Escala | **5M+ LOC, 8 repos, multi-lenguaje** (Python+TS+JS) en un grafo | `core/orggraph.py` |
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

**macOS / Linux** (una línea, como opencode):

```bash
curl -fsSL https://raw.githubusercontent.com/manzzaano/leo-code/main/install.sh | bash
```

**Windows**:

```powershell
powershell -c "irm https://raw.githubusercontent.com/manzzaano/leo-code/main/install.ps1 | iex"
```

O directo con tu gestor de tools:

```bash
uv tool install leo-code       # o: pipx install leo-code
```

Deja tres ejecutables en el PATH: `leo-code` (agente + TUI), `leo-code-mcp-stdio`
(servidor MCP) y `leo-code-mcp` (servidor HTTP).

Para desarrollo:

```bash
git clone https://github.com/manzzaano/leo-code.git && cd leo-code && pip install -e .
```

```bash
# Variables de entorno según proveedor del agente
export DEEPSEEK_API_KEY=sk-...      # o ANTHROPIC_API_KEY / OPENAI_API_KEY
```

## Uso

### Producto 1 — el agente

```bash
leo-code            # CLI del agente (usa el motor: inyecta contexto + tools deterministas)
leo-code tui        # cockpit full-screen: chat + grafo en vivo + medidor de tokens ahorrados
```

La TUI funciona **sin API key**: `/trace` `/impact` `/guard` `/who` `/where` son
deterministas (cero LLM). `/compare X` enseña lado-a-lado lo que un agente grep+read
habría gastado en la misma pregunta (tokens, archivos, $) — el contrafactual, visible.

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

**Claude Code** (una línea):

```bash
claude mcp add leo-code -- python -m leo_code.server.mcp_server
```

o `.mcp.json` del proyecto (este repo ya trae uno):

```json
{
  "mcpServers": {
    "leo-code": { "command": "python", "args": ["-m", "leo_code.server.mcp_server"],
                  "env": { "LEO_REPO": "." } }
  }
}
```

**opencode** — `opencode.json` (este repo ya trae uno):

```json
{
  "mcp": {
    "leo-code": { "type": "local", "command": ["python", "-m", "leo_code.server.mcp_server"],
                  "enabled": true }
  }
}
```

Tools que expone: `get_context` (subgrafo comprimido, ~80% menos tokens) +
`trace` / `impact` / `who_calls` / `where` / `guard` (deterministas, con prueba
`archivo:línea`, cero LLM). `guard` marca además qué afectados están **sin test**
antes de que tu agente edite.

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
pytest                                  # suite (147 tests)
python benchmark/audit.py               # 9 promesas medidas, exit 0 solo al 100%
python benchmark/audit_formal.py <repos># verificación FORMAL vs oráculos (ast / tsc)
python benchmark/token_efficiency.py    # reducción de tokens + recall (determinista)
python benchmark/mcp_client_bench.py    # producto 2 end-to-end vía cliente MCP real
```

---

## Licencia

MIT.
