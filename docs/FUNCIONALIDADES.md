# Funcionalidades de leo-mcp (inventario 2026-10-27, v0.3.3)

Inventario completo del producto, por importancia. Cada funcionalidad se revisa una a una
(investigación + opciones de mejora); la decisión del usuario se anota en "Revisión".

- **Crítica**: sin ella no hay producto.
- **Alta**: el diferencial frente a un agente sin leo-mcp.
- **Media**: hace que se use bien y sea fiable.
- **Baja**: configuración, diagnóstico y detalles.

## Crítica

| # | Funcionalidad | Dónde | Revisión |
|---|---|---|---|
| 1 | Servidor MCP stdio, 2 tools, versión del paquete | `server/mcp_server.py:47,97` | 27/10 decidido A+B+C: migrado a SDK `mcp>=2.3,<3` (handlers `on_*`, errores → `is_error` a mano, `stdio_server` v2 + `sys.stdout→stderr` tras el claim); `title` + `annotations` read-only. Hecho, sin publicar |
| 2 | `get_context`: símbolos relevantes con firma, cuerpo y `fichero:línea`, comprimidos | `mcp_server.py:278`, `engine.py:481` | 27/10 decidido A+B+D: benchmark NL `nl_retrieval_bench.py` (gate CI 60%) 20% → 67%; BM25 con tokenizador de código, exactos sin ruido, tests al final; `code_gen` → code_query; enum `task_type`; salida en inglés. C (PageRank personalizado) pendiente según benchmark. Hecho, sin publicar |
| 3 | `graph op=where`: definición de un símbolo | `core/graphquery.py:576` | 27/10 decidido A+B+C: sin imports si hay definición (+ «imported in N files»), `Clase.método`, firma por resultado, producto antes que tests/benchmarks. D (filtro por ruta) descartado. Hecho, sin publicar |
| 4 | `graph op=who_calls`: llamadores directos con líneas exactas de llamada | `mcp_server.py:242`, `graphquery.py:613` | 27/10 decidido A+B+C+D: callers de UNA def (`Clase.método` o nombre único) con la resolución ya existente (−25% callers django, −43% leo-code; nombres calientes casi igual, `x.save()` va por nombre); con homónimos avisa y propone `Clase.método`; producto antes que tests + «showing 50 of N (K in tests/benchmarks)»; caller como `Clase.método`; líneas de llamada con `ast` en Python (sin docstrings/comentarios, solo las que van a esa def). Peor caso django `get` (4.126 callers) 84 ms → 1,1 s, p95 6,9 ms. Hecho, sin publicar |
| 5 | `graph op=impact`: dependientes transitivos | `graphquery.py:670` | 27/10 decidido A2+B+C+D: nodos por definición (id) subiendo por la resolución (`callers_of_def`); antes deduplicaba por nombre y perdía dependientes homónimos (150/300 nombres leo-code) y no era determinista (84/300 → 0/300; django 40 → 0). `Clase.método` como raíz. Corte exacto con «stopped at N; more dependents exist» + «K of them in tests/benchmarks». Cada dependiente «← via X · depth N» en vez de la línea `edges:`. `callers_of_def` no cruza a otro lenguaje con homónimo propio (salvo HTTP). Auditoría (b) 0 falsos, (c) recall intacto; latencia django media 0,45 → 1,5 ms (máx 41). Hecho, sin publicar |
| 6 | `graph op=trace`: camino de llamadas A → B (≤12 saltos) | `graphquery.py:755` | 27/10 decidido A+B+C+D: BFS por definición (id) con la resolución (`_hops`: resueltas exactas, sin resolver → todas las homónimas), citando la def recorrida con nombre cualificado; antes iba por nombre y citaba `_resolve(n)[0]` (django: 4/203 caminos coherentes → 125/174; no determinista 112/200 → 0/200; leo-code 23/200 → 0, 0 saltos imposibles). Cada salto «called at :L» / «via HTTP», y «≈ by name[, N candidates]» si no está resuelto (62% de caminos tienen alguno). Clase solo como origen (no como salto intermedio). Nota si un extremo tiene homónimas; si un extremo no está en el repo lo dice y sugiere who_calls. Latencia django p50 261 → 339 ms (p95 576, máx 924). Pendiente E: preferir caminos con menos saltos por nombre. Hecho, sin publicar |
| 7 | `graph op=guard`: impact + qué dependientes no tienen test | `core/guardian.py:119` | |
| 8 | Índice del código: símbolos y llamadas | `rag/indexer/`, `engine.py:289` | |
| 9 | Análisis completo de Python (`ast`) y TS/TSX/JS (tree-sitter) | `core/parser.py`, `core/parser_ts.py` | |
| 10 | Instalación: PyPI (`uv tool install` / `pip`) y npm (`npx -y leo-mcp`) | `pyproject.toml`, `npm/` | |

## Alta

| # | Funcionalidad | Dónde | Revisión |
|---|---|---|---|
| 11 | Exactitud del grafo comprobada en CI (100% vs `ast` y `tsc`) | `benchmark/audit_formal.py`, `audit.yml` | |
| 12 | Resolución de llamadas Python (imports, MRO, tipos locales): 74,9% django / 80,2% sympy exactas, recall 100% | `graphquery.py:95-466` | |
| 13 | Enlace frontend `fetch` → ruta backend | `core/boundary.py:136` | |
| 14 | Hook de aviso antes de editar (Claude Code) | `guard_hook.py` | |
| 15 | └ Nunca bloquea, siempre sale con 0 | `guard_hook.py:1-20` | |
| 16 | └ Silencio en tests, archivos nuevos/no código, fuera del repo, sin índice, índice >4 MB o >2 s | `guard_hook.py:141` | |
| 17 | └ Dependientes que son tests = cobertura, no riesgo | `guard_hook.py:115` | |
| 18 | Indexado incremental con vigilancia de archivos | `engine.py:179-188` | |
| 19 | Instrucciones del servidor (cuándo usar cada tool) | `mcp_server.py:41` | |
| 20 | `leo-mcp init` para Claude Code, Cursor, opencode y Codex (+ hook en Claude Code) | `cli.py:254` | |
| 21 | └ Actualiza configuración antigua conservando claves del usuario | `cli.py:254` | |
| 22 | └ Sin hook si corre desde la caché de uv | `cli.py:28-62,234` | |
| 23 | Contexto autosuficiente (cuerpos ≤1400 car., sin inflar presupuesto) | `engine.py:481` | |

## Media

| # | Funcionalidad | Dónde | Revisión |
|---|---|---|---|
| 24 | Búsqueda combinada: exactos + BM25 + scorer (PageRank, TF-IDF) + RRF | `engine.py:540-640` | |
| 25 | Siglas cortas solo si señalan 1-2 archivos | `engine.py:442` | |
| 26 | Archivo o directorio nombrado en la consulta va primero | `engine.py:560-600` | |
| 27 | Tipo de tarea detectado → presupuesto de tokens; `task_type` forzable | `rag/classifier.py:25` | |
| 28 | `budget_tokens` | `mcp_server.py:66` | |
| 29 | Reintento como consulta de código si se clasifica `no_code` | `mcp_server.py:291` | |
| 30 | Aviso «no symbol matched» (0.3.3) | `mcp_server.py:304` | |
| 31 | Cabecera de ahorro de tokens | `mcp_server.py:307-314` | |
| 32 | Lista de archivos fuente al final | `mcp_server.py:298` | |
| 33 | Siguiente paso sugerido en `graph` (`[next]`) | `mcp_server.py:188` | |
| 34 | Símbolo desconocido → hasta 5 parecidos | `mcp_server.py:179` | |
| 35 | `trace` sin camino explica por qué | `mcp_server.py:259` | |
| 36 | Errores claros (op, argumentos, `repo_path`, `query` vacía) | `mcp_server.py:107,234` | |
| 37 | Rutas relativas al repo | `mcp_server.py:101` | |
| 38 | Varios repos por sesión, caché de 4 grafos | `mcp_server.py:141-170` | |
| 39 | Índice en caché de usuario, nunca en el repo | `engine.py:31-41` | |
| 40 | Reconstrucción si cambia `_INDEX_FORMAT` | `engine.py:210` | |
| 41 | Escritura agrupada (3 s) y bloqueo entre procesos | `engine.py:54-77,179` | |
| 42 | Arranque sin bloquear; no indexa `$HOME` ni la raíz | `mcp_server.py:365,387` | |
| 43 | Precarga de librerías nativas (Windows); stdout solo para el protocolo | `mcp_server.py:378,410` | |
| 44 | Exclusiones del índice (deps, build, minificados, >512 KB, `.gitignore`) | `rag/indexer/watcher.py:73-77` | |
| 45 | Análisis aproximado de otros 22 lenguajes | `core/parser_generic.py` | |
| 46 | Aviso a partir de 250k símbolos | `engine.py:195` | |
| 47 | `leo-mcp doctor` | `cli.py:124` | |
| 48 | `leo-mcp index` (símbolos por lenguaje, top 5 más dependidos) | `cli.py:92` | |
| 49 | Comando escrito por `init`: binario instalado o `uvx` con versión fijada, nunca `npx` | `cli.py:62` | |
| 50 | Launcher npm: `uvx` o venv privado; stdout limpio en modo servidor | `npm/bin/leo-mcp.js` | |

## Baja

| # | Funcionalidad | Dónde | Revisión |
|---|---|---|---|
| 51 | Búsqueda semántica opcional (`LEO_SEMANTIC`, extra `semantic`) | `engine.py:131`, `mcp_server.py:342` | |
| 52 | └ Arranque rápido sin esperar al modelo (`LEO_FAST_START`) | `engine.py:618` | |
| 53 | Variables de entorno del producto | varios | |
| 54 | Logs en la caché de usuario | `mcp_server.py:411` | |
| 55 | `leo-mcp serve` y `--version` | `cli.py:296` | |
| 56 | `init --no-hook` | `cli.py:310` | |
| 57 | Codex: `init` imprime TOML | `cli.py:254` | |
| 58 | Alias `leo-code-mcp-stdio` | `pyproject.toml:59` | |

## Existe pero no está en el MCP

| # | Funcionalidad | Nota | Revisión |
|---|---|---|---|
| 59 | `GraphQuery.callees` (qué llama un símbolo) | `graphquery.py:589`; no es op de `graph` | |
| 60 | Guardian sobre un diff (`python -m leo_code.core.guardian`) | usado en `guardian.yml`; no documentado para usuarios | |

## Fuera del producto, aunque esté en el paquete

| # | Qué | Nota | Revisión |
|---|---|---|---|
| 61 | Servidor HTTP antiguo `leo-code-mcp` (extra `http`) | se cae con >1 worker; `usage.jsonl` en `~/.leo-code` | |
| 62 | Agente TUI, `rag/agent`, `session/`, plugins | agente antiguo | |
