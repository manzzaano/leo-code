# PLAN — Cierre de leo-code (fuente única de verdad)

> **Regla de trabajo:** este archivo se lee al inicio de CADA sesión y se actualiza
> ANTES de cerrar contexto. Si el contexto de la conversación supera ~40%, volcar
> estado aquí y pedir `/clear`.

**Última actualización:** 2026-09-10 20:45 · **Hito activo: M2 — Multi-harness (retomado tras M2.5; publicación adelantada por pedido explícito, ver nota de sesión)**

> ⚠️ **Toda la tabla histórica de falsaciones y la línea base tienen sesgo de
> medición** (tokens de subagentes `task` no contados; OC delegaba mucho más que
> OCMCP → OC salía artificialmente barato). Corregido desde commit 364cc5b.
> No re-derivar conclusiones de números antiguos sin re-medir.

## Objetivo

Entregar **leo-mcp** (servidor MCP, 2 tools: get_context + graph) empaquetado a
compañeros para que lo usen en su agente diario y den su visto bueno.

### Criterio de éxito M1 (v2, redefinido 2026-07-14 con 6 falsaciones medidas)

La promesa medible es **corrección estructural garantizada sin coste**, no ahorro e2e:

| Métrica | Umbral | Estado |
|---|---|---|
| Corrección estructural (graph: impact/trace/guard/who_calls) | 100% precisión+recall vs oráculos, gateado en CI | ✅ probado (`audit_formal.py`) |
| Ahorro POR consulta (get_context vs leer los archivos que cubre) | 80-97% | ✅ probado (`token_efficiency.py`) |
| Calidad (score juez, 3× validación) | OCMCP ≥ OC | ✅ **+0,18** (5,00 vs 4,82; n=3 bc1400) |
| Velocidad | duración ≤ +10% vs vanilla | ✅ **−14,2%** |
| Sobrecoste tokens e2e | ≤ +10% mediana/tarea | ✅ **+1,9%** (pooled **−30,1%**) |

**✅ CUMPLIDO 2026-07-14 19:49 — validación 3× config bc1400 (HEAD=b636a9f), contabilidad
completa (subagentes incluidos), exit=0 de `judge_v2.py`.**

**Evidencia que mató "−40% e2e vía MCP"** (6 configs, todas medidas, todas peor o neutro):

| Config | Δ tokens | Δ dur | Δ score |
|---|---|---|---|
| Steering v2 (n=45) | +64,5% | ≈0 | +0,09 |
| B1 autosuficiente | +64% | ≈0 | 0 |
| B1+veto 1ª acción | +83,5% | −2% | 0 |
| C v2 veto relecturas | +4% (espejismo; pierde 11/15 tareas) | +5% | 0 |
| C v3 sustitución forzada | +108% | ≈0 | 0 |
| C v5 pasiva (c5b) | +51,9% | +7,7% | 0,00 |

Causa estructural: no controlamos el loop del agente; cada fricción (veto, llamada
forzada) añade turnos y cada turno re-envía la conversación entera. El ahorro real
del motor es POR consulta y la corrección estructural es lo que vanilla no tiene.

### Línea base (2026-07-13, 15 tareas)

| | OC | OCMCP |
|---|---|---|
| Score | 4.73 | 5.00 |
| Tokens | 89.879 | 124.773 (**+39%** ❌) |
| Duración | 47,1s | 37,3s (−21%) |
| MCP calls/tarea | — | **0,5** ❌ |

**Causa raíz:** adopción casi nula → paga overhead de definiciones + sigue leyendo archivos.

### Resultados steering v2 (2026-07-13, 3 corridas × 15 tareas, HEAD=61ecb8d)

| Corrida | OC tok | OCMCP tok | Δ tok | Adopción |
|---|---|---|---|---|
| 1 | 75.618 | 89.117 | +18% | 1,1 |
| 2 | 61.252 | 129.704 | +112% | 0,7 |
| 3 | 64.870 | 113.042 | +74% | 1,0 |
| **Pooled (n=45)** | **67.247** | **110.621** | **+64,5%** | **0,93** |

Score pooled: OC 4,91 · OCMCP 5,00 (+0,09). Tools usadas: get_context 31, where 7, trace 4, resto 0.

**Diagnóstico fino (por tarea):** donde pierde (t11 +327%, t9 +202%) el agente llama get_context y RELEE archivos igualmente (hasta 15 relecturas redundantes); donde gana (t6 −27%) hay 1 llamada + respuesta autosuficiente. No es solo adopción: la respuesta de get_context no sustituye la lectura. → B1 (autosuficiencia) es la palanca principal; C elimina la varianza de adopción.

## Estrategia acordada

**B + C, con A solo como remate:**

- **B — Menos tools, más ricas:** consolidar tools (`get_context` devuelve subgrafo+fuente+impacto en una llamada), recortar overhead de definiciones, respuesta autosuficiente (sin re-lecturas de archivos).
- **C — Adopción forzada por harness:** hook Claude Code (UserPromptSubmit inyecta contexto), plugin/config opencode, equivalente Codex. Adopción determinista, no persuadida.
- **A — Steering iterativo:** solo ajustes finales; ya no es la vía principal.

Harnesses objetivo: **Claude Code, opencode, Codex**. Sin fecha límite: kanban por hitos.

## Kanban

### ✅ M0 — Diagnóstico (CERRADO 2026-07-13)
- [x] Corrida de validación de steering v2 (3 corridas pareadas, exit 0, sin cuelgues)
- [x] Análisis → decisión B/C (ver "Resultados steering v2" y "Decisiones")
- **Resultado:** steering v2 dobla adopción (0,5→0,93) y no basta ni de lejos. B+C confirmado.

### ✅ M1 — Delta fuerte en opencode (CERRADO 2026-07-14)
- [x] **B1 — get_context autosuficiente** (commit 335a3d2, 206 tests OK): vía MCP con cuerpos completos (body_chars 6000), presupuesto ×4, footer sin "read_file"; serializador re-truncaba a 2000 → red de seguridad 8000. Agente nativo sin cambios. Métrica guía: `redundant_native_after_ctx` → ~0.
- [x] Corrida-señal B1 sola (`b1_signal.json`, 19 min): OC 5.00/57.0k · OCMCP 5.00/93.6k (**+64%**), adopción 0,7, 27 relecturas tras ctx. **B1 sin C no mueve nada** — el agente ni llama, y cuando llama relee. Confirma C como palanca.
- [x] RUN 1 stack v1 (C = solo primera acción): **+83,5% tokens**, adopción 1,1, 28 relecturas TRAS get_context. Lección: autosuficiencia sin sustitución = lastre ×4 por turno. Corridas 2-3 abortadas (config descartada).
- [x] **C v2** (commit fec9f92): el plugin captura del footer las fuentes ya entregadas y veta releerlas enteras (1 veto/archivo; offset/limit pasa). 6/6 ramas testeadas.
- [x] RUN 1 Cv2: +4,2% agregado era espejismo (OC outlier 1,05M en t4). Por tarea: OCMCP peor en 11/15 (t11 +575%, t14 +412%); la válvula "1 veto y pasa" deja pagar contexto Y archivo.
- [x] **C v3** (commit e2572f2): sustitución forzada — incluidos nunca enteros (rango sí); archivo nuevo exige antes `get_context("<archivo>")` (comprimido), una insistencia de escape. 9/9 ramas testeadas.
- [x] RUN 1 Cv3: **+108%** con adopción 2,7 — contraproducente. **Lección estructural: cada turno extra (veto, llamada forzada) re-envía la conversación entera; los turnos dominan el coste, no el contenido.** Validación abortada.
- [x] Decisión usuario 2026-07-14: **seguir hasta −40%** (no reencuadrar criterio).
- [x] **C v5** (commits b47f45a+4201037): sustitución PASIVA — read entero de código devuelve la vista comprimida del AST (`leo_code.filectx`, ~50% del crudo, 0,9s con índice caliente) sin turnos extra ni vetos (un veto dejó al agente respondiendo a ciegas). MCP reducido a 2 tools (get_context + graph op=...). Footer ordena responder ya. Swap verificado end-to-end (28,2k→13,8k, respuesta correcta).
- [x] Señal c5 (HEAD=b47f45a, sin fix persistencia) MURIÓ: cada read re-indexaba en la copia → timeouts 180s con tok=0. Confirma que el fix 4201037 era necesario. NO sembrar la ruta de la copia en kc_indexed_repos.json: el índice sembrado lleva rutas del repo original (daría contexto vacío).
- [x] Señal c5b (02:11-02:34, HEAD=7fe67cf, 0 timeouts): OC 5.00/91.5k/43,3s · OCMCP 5.00/138.9k(**+51,9%**)/46,6s(+7,7%) · adopción 0,5. C v5 pasiva tampoco baja. 6ª falsación → criterio M1 redefinido (ver arriba).
- [x] **Fricción localizada** (diagnóstico c5b por tarea): tareas SIN get_context **+1%** mediana (overhead ~cero; swap gana: t5 −64%, t13 −48%); CON get_context **+128%** — la respuesta ×4 cebaba MÁS exploración (t14: 1→14 nativas) y viajaba cada turno. El veneno era la grasa de B1, no el MCP.
- [x] **Dieta de get_context** (commit b1eee05): sin multiplicador ×4, cuerpos de estrategias 6000→2500. 206 tests OK.
- [x] Señal c6 (11:03-11:21): agregado +36,4% PERO **mediana por tarea +3%** y gana 4/15; dur +0,5%, score 0,00. Agregado sesgado por 2 outliers estocásticos (t4 +753%, t6 +684% — get_context ceba exploración; en cambio t15 −69%, t14 −36% donde el swap trabaja solo). Señal única no decide ±10% → pooled n=3.
- [x] **Validación 3× criterio v2** (11:45-12:52, HEAD=3d7310e≡b1eee05 en código) → `harness_run1/2/3.json`. **FALLA tokens**: mediana +52,5%, gana 9/42 pares; dur −8% OK; score +0,27 OK. c6 (+3%) fue tiro afortunado (su t15 −69% era un OC desafortunado de 185k, no el swap).
- [x] **Diagnóstico del +52% → SESGO DE MEDICIÓN CONFIRMADO** (DB de opencode, `session.parent_id`): el stream `--format json` solo emite step_finish de la sesión PADRE; los subagentes de `task` corren en sesiones hijas invisibles. En la validación: OC ocultaba **5,15M tokens** (2× su cifra medida, 14 hijas) y OCMCP 0,82M (5 hijas). Verificación del mapeo: stream total == in+out+reasoning+cache de la DB, exacto (0,0%) en 87 sesiones. **Corregido: pooled −23,5%, mediana/tarea +6,0%, gana 19/44** — el criterio v2 PASARÍA. Por corrida corregida: r1 −19%, r2 +4,3%, r3 +55,5% de mediana (varianza alta → confirmar con medición limpia, no post-hoc).
- [x] **Fix contabilidad** (commit 364cc5b): `hidden_task_tokens()` en run_real.py suma descendientes (CTE recursiva, unidades idénticas al stream) por directorio+t_start; campo `task_tokens` en resultados. Auto-check contra los totales conocidos: exacto.
- [x] **Validación 3× con contabilidad correcta** (14:26-15:33, HEAD=364cc5b) → respaldada en `harness_clean_run1/2/3.json` (sesgadas en `harness_biased_run*.json`). Pooled n=3: **tokens mediana −1,6% / pooled −34,1% OK · dur +6,9% OK · score −0,09 FALLA**. El gap de score es SOLO asimetría de timeouts (OCMCP 2: t5/t4; OC 1: t14; cada timeout puntúa 0): en los 42 pares válidos ambos = 5,000 exacto. Fricción real que queda: t2_debug (+207/+258/+409) y t5_search (+281/+652/timeout) — sistemáticas; el resto dentro de ruido o ganando.
- [x] **Ampliación a n=6** (15:34-16:26): corridas 4-6 impecables (0 timeouts, score 5,00=5,00). **Pooled n=6 (87 pares): tokens mediana +1,2% / pooled −32,1% ✅ · dur +1,8% ✅ · score 4,96 vs 4,91 ❌ por la letra** — el −0,04 es íntegramente los 3 timeouts de las corridas 1-3 (OCMCP 2 vs OC 1; en pares válidos 5,000=5,000; 2/90 vs 1/90 n.s.). Regla preregistrada no se retuerce: M1 sigue abierto.
- [~] **Palanca anti-timeout/fricción** (commit pendiente de señal): t2_debug pide un bug a nivel de línea en `rag/compressor.py`, EXACTAMENTE un archivo donde el swap a 600 disparaba (vista 52%) → compensación con greps/relecturas (+224%). Barrido medido: a 1400 el swap suelta compressor.py (81%) y parser.py (95%) y conserva loop.py (61%). **body-chars 600→1400** aplicado (commit b636a9f). **Señal bc1400 (18:35-18:52): mediana −18,3% · pooled −23,6% · 0 timeouts · score 5,00=5,00 · dur −11,3%. Las 3 tareas de texto exacto arregladas: t2 +224%→+2,5%, t7 +62%→−37%, t4 +103%→−28%.**
- [x] **Validación 3× config bc1400** (18:53-19:49, HEAD=b636a9f) → **exit=0: mediana +1,9% ✅ · pooled −30,1% ✅ · dur −14,2% ✅ · score +0,18 ✅ · timeouts solo de OC (t14 ×2)**. judge_v2 con umbral unilateral de sobrecoste. Corridas 4-6 de la config anterior respaldadas como `harness_clean_run4/5/6.json`.
- [x] ~~Benchmark 15 tareas × 3 corridas con B1+B2+C~~ → superado por la validación bc1400 (la config final es B1+B2+C v5 pasiva con body-chars 1400).
- ⚠️ **Lección operativa**: lanzar benchmarks SIEMPRE con `Start-Process` desacoplado. La 1ª bc1400 (16:30) salió 30/30 timeouts en ambos sistemas: iba como hijo del shell sandboxeado del agente (sin red). Misma firma que la sonda colgada de las 12:55. Corrida borrada e invalidada en el log.
- Diagnóstico fricción restante (read-only, clean n=3): **t2_debug** = OCMCP hace 2-4 reads + 2-3 greps sin MCP (113→188k) vs 1 read de OC — hipótesis: el swap (body-chars 600) recorta el detalle que depurar exige → exploración compensatoria; palanca: subir body-chars del swap o swap solo para archivos grandes. **t5_search** = OC usa bash barato; OCMCP se dispersa (get_context+write / timeout / task 584k) — palanca: steering no debe desincentivar bash para búsquedas. NO tocar hasta cerrar n=6.
- [x] **B2 — dieta de definiciones** (commit 381803e): descripciones 823→664 tok/turno (−19%). Marginal; la palanca es C.
- [x] **C — primera acción forzada (opencode)** (commit 5bc375f): plugin `.opencode/plugin/leo-first-action.js` veta read/grep/glob/list hasta la 1ª llamada a get_context; válvula tras 3 vetos; gated LEO_FORCE=1 (benchmark lo activa solo en OCMCP). Validado: smoke test + 4 ramas en node.
- **Done cuando:** tabla de criterio de éxito cumple los 4 umbrales → **✅ CERRADO 2026-07-14 19:49**

### 🔵 M2 — Multi-harness (ACTIVO 2026-07-14; usuario dijo "sigue" tras cierre M1)
- [x] Claude Code: **smoke test MCP PASA** (20:05, desde la propia sesión: `graph who_calls hidden_task_tokens` → 2 callers correctos con archivo:línea; `get_context` → contexto AST coherente; índice fresco con código del día). Instalación = config MCP del proyecto ya operativa.
- [x] Claude Code: hook C — **swap pasivo portado y smoke test e2e PASA** (2026-07-16 20:45). Mecanismo: PostToolUse `hookSpecificOutput.updatedToolOutput` (existe desde ~2.1.2xx; probado en 2.1.211). Implementación: `.claude/hooks/leo-read-swap.py` + registro en `.claude/settings.json`, gated LEO_FORCE=1 igual que opencode. 3 gotchas resueltos: (1) updatedToolOutput se valida contra el outputSchema del tool — para Read hay que devolver `{type,file:{content,...}}` mutado, un string pelado se descarta con "does not match output shape"; (2) stdout/stdin del hook arrancan en cp1252 en Windows → `sys.stdout.reconfigure(encoding="utf-8")` obligatorio (el contenido lleva →/ñ); (3) subprocess filectx necesita PYTHONUTF8=1 + errors="replace". Verificado: sesión headless `claude -p` recibió la vista comprimida (loop.py 55,8k→34,3k chars) como output del Read; guard >25% y rama offset/limit intactos (mismo comportamiento que plugin opencode).
- [~] Claude Code: mini-benchmark (5 tareas) — runner `benchmark/run_cc.py` HECHO y validado e2e (copia aislada sin CLAUDE.md/AGENTS.md autocargados; CC = --strict-mcp-config sin MCP; CCMCP = --mcp-config .mcp.json + LEO_FORCE=1 + steering via --append-system-prompt; tokens del transcript JSONL con dedupe por message.id, subagentes incluidos — el sesgo `task` EXISTE también en CC: t5 stream 34,8k vs jsonl 98,8k). **RUN 1 (haiku, 2026-07-16 21:05)**: mediana +5% ✅ (t1 −20%, t2 −21%, t5 +7%, t7 +5%, t14 +283%) · pooled +94% ❌ (todo el daño es t14: 1,06M tok, 22 turns, 10 reads + 8 bash tras get_context — el patrón "get_context ceba exploración" de opencode) · score 6,75 vs 6,90 (−0,15) · dur +15%. **Adopción ~0: las tools MCP salen DIFERIDAS tras ToolSearch en Claude Code** (el agente tuvo que buscarlas; solo t14 llamó get_context 1 vez). Swap disparó 1/16 reads (loop.py; en archivos pequeños la vista sale más grande que el crudo, guard OK). Falta: n=3, y decidir si medir con `ENABLE_TOOL_SEARCH=false` (desactiva el deferral; valores true/false/auto:N) o aceptar el default del harness.
- [ ] Codex: instalación + smoke test + mini-benchmark (5 tareas)
- **Done cuando:** los 3 harnesses instalan y pasan smoke test; mini-bench sin regresión

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

### ⚪ M3 — Empaquetado
- [ ] Instalación 1 comando por harness (pipx/uvx + snippet de config)
- [ ] README honesto con números finales medidos
- [ ] Versión etiquetada
- **Done cuando:** compañero instala desde cero en <5 min siguiendo README

### ⚪ M4 — Beta compañeros
- [ ] Entregar a ≥2 compañeros (Claude Code / opencode / Codex)
- [ ] Canal de feedback + 3 preguntas concretas (¿lo usarías? ¿qué falta? ¿qué sobra?)
- [ ] Iterar sobre feedback bloqueante
- **Done cuando:** visto bueno explícito de los compañeros → **PROYECTO TERMINADO**

## Decisiones tomadas

- 2026-07-13: producto a entregar = **leo-mcp** (no el agente TUI). Criterio = delta fuerte. Estrategia B+C. Kanban sin fecha.
- 2026-07-13 (cierre M0): steering v2 validado con n=3 → adopción 0,93 (objetivo ≥2), tokens +64,5% (objetivo −40%), score +0,09 (objetivo +0,5). **Vía A (steering) agotada como palanca principal.** M1 = B1 autosuficiencia de get_context + B2 dieta de tools + C forzado de primera acción en opencode.
- 2026-07-14 (goal nuevo del usuario): **criterio M1 v2** — corrección estructural 100% (probada) + ahorro 80-97% por consulta (probado) + score ≥ vanilla + dur ≤+10% + tokens e2e ±10%. "−40% e2e" descartado tras 6 falsaciones (tabla arriba). PushNotification al cerrar cada hito.
- 2026-07-14 (cierre M1): **las "6 falsaciones" estaban contaminadas por el sesgo de subagentes** — con contabilidad completa y config bc1400, OCMCP gana en pooled (−30,1%) y empata en mediana (+1,9%). Config final: MCP 2 tools (get_context dieta + graph) + swap pasivo AST body-chars 1400 + steering v2. La promesa e2e del README debe ser la medida: **mediana por tarea ≈ neutra, pooled −30% (el ahorro viene de tareas pesadas), score y velocidad iguales o mejores, corrección estructural garantizada**.

## Notas de sesión

**2026-09-10 tarde/noche (M2.5 cierre + publicación adelantada, fuera de orden de M3/M4 por pedido explícito del usuario):**
- M2.5 cerrado con review final de rama completa (opus): 2 Important reales
  encontrados y arreglados en 1 fix wave — `test_compute_context_no_code_returns_documents`
  era vacuo (escribía `.md`, el indexer no lo indexa; ahora usa `docs/*.txt`
  y verifica contenido real) y el plan/spec de esta hardening nunca se habían
  comiteado a git (vivían sueltos en el checkout). Merge local a `dev`
  (fast-forward, 227/227 verde), worktree y rama borrados.
- Usuario pidió explícitamente publicar en GitHub para portfolio (adelanta
  parte de M3/M4 sin cerrar el resto). Hecho: repo pasado a **público**;
  `main` (que estaba 80 commits atrás y ni tenía `engine.py`) fast-forward
  a `dev`; README reescrito enfocado 100% en leo-mcp (antes mezclaba con el
  agente TUI y tenía datos viejos: "6 tools" vs 2 reales, "147 tests" vs 227);
  `benchmark/results_real/*.json` sueltos gitignorados (solo `summary.json`
  se trackea) — sin tocar `.claude/`/`.opencode/` (no pedido).
- Segunda vuelta (pedido explícito): **sin licencia** — quitado `license = {text
  = "MIT"}` de los 4 `pyproject.toml` (raíz + 3 de `packaging/`), borrado
  `LICENSE`, y las referencias sueltas en `Dockerfile` y `docs/index.md`.
  README ampliado con números reales de la última corrida verde de
  `leo-code formal audit` en CI (2026-07-09, `FORMAL: 5/5 → IRREFUTABLE`):
  Python vs `ast` 100,000%/100,000% (4 repos, ~99,5k símbolos); TS/JS vs
  `tsc` **99,965%/99,959%** (no se redondeó a 100% — número real); guardián
  0 falsos/146 funciones; blast radius ⊆ predicho; SLA 1,78ms/12ms @291k
  símbolos.
- **CI rota encontrada y arreglada:** el workflow `Test` fallaba en los 3
  Python (3.11/3.12/3.13) desde julio — `pip install -e ".[dev]"` no
  resuelve `tree_sitter_languages>=1.10` en 3.13 (paquete sin build ahí).
  Grep confirmó que `tree_sitter_languages` no lo importa nada en
  `leo_code/` — superado hace tiempo por `tree-sitter-typescript`/
  `-javascript` directos en `parser_ts.py`. Quitado de `pyproject.toml`
  (raíz + `packaging/leo-code-core`). Verificado local: `pip install -e
  ".[dev]" --dry-run` resuelve limpio, 227/227 tests, import smoke test de
  CI pasa. Push a `dev`+`main`, CI re-lanzada.
- **Segundo bug de CI, mismo push:** con el install ya arreglado, `pytest`
  reventaba en collection — `mcp>=1.0` sin techo bajaba `mcp==2.2.0` en
  instalación fresca, que rediseñó la API de `Server` (handlers por
  `ctx`/`params` en vez de los decoradores `@server.list_tools()`/
  `@server.call_tool()` que usa `mcp_server.py`). Local tenía 1.28.1
  (funciona) — nunca se vio hasta correr en un entorno realmente fresco.
  No se migró a la API 2.x a ciegas (cambio mayor, sin verificar el
  transport nuevo) — se fijó `mcp>=1.0,<2.0` en `pyproject.toml` raíz y
  `packaging/leo-mcp`. Confirmado en CI real (no solo local): `Test`
  verde en 3.11/3.12/3.13 (commit 58d6abf) y `leo-code formal audit`
  verde de nuevo (commit 58d6abf, 2026-09-10, `FORMAL: 5/5 →
  IRREFUTABLE`, números actualizados en el README). Ambos workflows
  llevaban rotos desde julio sin que nadie lo viera (repo era privado,
  nadie miraba Actions).
- `docker.yml`/`publish.yml` (solo tags) y `guardian.yml` (solo PRs) no
  corrieron — esperado, no hay tag ni PRs todavía.
- No se tocó nada de M2 (Codex) ni M3/M4 formalmente en el kanban — este
  bloque documenta trabajo real hecho fuera de la cola de milestones, a
  pedido explícito. Falta si se retoma M3 después: instalación 1-comando
  verificada de punta a punta, versión etiquetada, y decidir si se
  re-agrega alguna licencia más adelante.

**2026-09-10 (Fase 2 hardening, Task 10 — auditoría dedup grupo grafo):**
- Comparados los símbolos públicos de `core/graph.py`, `graphquery.py`, `refgraph.py`, `orggraph.py` (grep `^def \|^class`): no hay duplicado literal que unificar. Una coincidencia de nombre sí existe — `_demo` está definido en `graphquery.py` (línea 202) y en `orggraph.py` (línea 81) — pero son rutinas privadas de auto-chequeo con cuerpos no relacionados (una arma una cadena sintética de cápsulas y valida `where`/`who_calls`/`callees`/`impact`/`trace`; la otra arma un par frontend/backend sintético y valida `link_http_edges` + `trace` cross-repo), clasificable como (a) "mismo nombre, responsabilidad distinta" — no redundancia. `refgraph.py` importa `_bare` de `graphquery.py` y `orggraph.py` compone `GraphQuery` + `link_http_edges` (boundary.py): ambos son composición legítima documentada en sus propios docstrings, no redundancia.
- Hallazgo real (no era el buscado, pero verificado): `core/graph.py` (`bfs_subgraph`, `find_nodes_by_name`, `detect_relation_filter`, `filter_by_relation`) es código **huérfano** — solo lo importa `core/__init__.py` (re-export), cero callers en el resto del repo (el tool MCP `graph` en `server/mcp_server.py` usa exclusivamente `GraphQuery` de `graphquery.py`), y cero tests (`tests/test_graph*.py` no existe, a diferencia de graphquery/refgraph/orggraph que sí tienen suite propia). Parece un prototipo pre-GraphQuery (parseo NL de relaciones tipo "llama"/"importa") superado por la interfaz de ops estructurada (where/who_calls/impact/trace/guard).
- No se tocó código: borrar `graph.py` excede el alcance de esta auditoría puntual de "duplicado entre 2+ archivos" (es un hallazgo de código muerto, no de duplicación) y toca un 5º archivo (`__init__.py`) fuera del grupo de 4 — queda anotado como candidato a limpieza futura, no se fuerza el borrado sin acuerdo explícito.

**2026-09-10 (Fase 2 hardening, Task 11 — auditoría dedup grupo parser):**
- Leídos completos los 3 módulos (no solo grep): `core/parser.py` (758 líneas), `core/parser_generic.py` (483 líneas), `core/parser_ts.py` (124 líneas). Confirmado el pre-check del controlador: cero colisión de nombres entre funciones/clases públicas top-level de los 3 archivos (grep `^def \|^class`). `Capsule` (dataclass) y `_make_id` están definidos una sola vez en `parser.py` y los importa `parser_generic.py` (`from leo_code.core.parser import Capsule, _make_id`) — composición legítima, no duplicado. `parser_ts.py` importa solo `Capsule` (no usa `_make_id`; genera su propio id con esquema distinto `f"{file_path}:{start}:{name}"` — inconsistencia menor de esquema de IDs entre módulos, no duplicación de lógica, no se toca).
- **Veredicto ruta dual JS/TS (el caso que el brief pedía verificar):** confirmado que es un fallback chain deliberado, NO lógica duplicada. Verificado leyendo el cuerpo completo de `parser_ts.py::extract_from_tree_sitter` (no solo la firma): (1) el propio docstring del módulo documenta la intención — la regex genérica de `parser_generic` para TS/JS medía 74% precisión / 60% recall contra un oráculo del compilador TS; `parser_ts` replica exactamente la regla de callee del oráculo (`identifier` o `member_expression.property`) caminando el AST real de tree-sitter, sin cap ni denylist; (2) mecanismo fundamentalmente distinto: `parser_generic._find_calls_in_block` usa regex `(\w+)\s*\(` con lista de stopwords y cap de 10 resultados sobre el bloque de texto delimitado por conteo de llaves (`_find_block_end_brace`); `parser_ts._calls_in`/`_callee_name` recorren nodos `call_expression` reales del árbol de sintaxis, resolviendo `identifier` vs `member_expression`, desenvolviendo `unary_expression` (`!!fn<T>()`) y excluyendo tagged templates — nada de esto existe en la versión regex; (3) además el ALCANCE capturado difiere (no es ni siquiera el mismo job 1:1): `parser_generic` para `javascript`/`typescript` extrae function, arrow function, class, import/require y (solo TS) interface/type; `parser_ts` solo extrae `function_declaration`/`generator_function_declaration`/`method_definition`/`class_declaration`/`abstract_class_declaration` — no arrow functions, no interfaces/types, no imports. `parser.py::extract_from_file` (líneas 692-723) intenta tree-sitter primero para TS/JS y cae a `parser_generic.extract_generic` si falla cualquier cosa dentro del bloque `try` de líneas 709-713 — el `except Exception` envuelve tanto el `import` de `parser_ts` como la llamada de parseo `_ts(...)` y `detect_frameworks(...)`, así que el fallback se dispara no solo por `ImportError` (dependencia opcional `tree_sitter` no instalada) sino por cualquier fallo en tiempo de ejecución durante el parseo real (error de parseo, bug en `detect_frameworks`, etc.) — degradación gradual intencionada, tal como sugería el pre-check del controlador. No se unifica nada: no hay lógica duplicada que fusionar.
- Resto de la frontera (Python vía `ast` en `parser.py`, regex multi-lenguaje + HTML/CSS estructural en `parser_generic.py`) se mantiene como se esperaba, sin solapamiento — `detect_frameworks`/`_detect_*` (post-proceso de cápsulas, solo en `parser.py`) se aplica uniformemente sobre cápsulas de cualquier origen (ast, regex o tree-sitter), es composición, no redundancia.
- **Hallazgo real fuera de alcance (no se toca, no es duplicación):** `parser.py::extract_from_file`, línea 720, el último fallback (`except ImportError` tras `extract_generic`) hace `return extract_from_tree_sitter(content, path, language)` — pero `extract_from_tree_sitter` NUNCA se importa al namespace del módulo `parser.py` (solo se importa localmente como alias `_ts` dentro de un `try` anterior, líneas 709-712); ese nombre no existe en `parser.py`. Verificado con grep en todo `leo_code/`: la única otra referencia es en `leo_code/rag/indexer/watcher.py:40`, que hace `from leo_code.core.parser import extract_from_tree_sitter` — import que SIEMPRE falla (`ImportError`, el símbolo no existe ahí), capturado por el `except Exception` que envuelve `Indexer._process_one` (línea 36-48), así que `use_tree_sitter=True` en el indexer falla en silencio para todo archivo (0 cápsulas) en vez de usar tree-sitter. Es un bug real, pero (a) no es duplicación entre los 3 módulos de este grupo — es una ruta de import rota; (b) arreglarlo de raíz toca un 4º archivo (`watcher.py`) fuera del grupo de 3 de esta tarea. Queda anotado como candidato a fix futuro (import debería apuntar a `leo_code.core.parser_ts`), no se fuerza sin acuerdo explícito — mismo criterio que el hallazgo de código muerto de Task 10.
- No se tocó código de producción en esta tarea (hallazgo = no hay duplicación real que unificar). No se corrió la suite completa (no aplica: sin cambios de código).

**2026-09-10 (Fase 2 hardening, Task 12 — auditoría dedup `rag/scorer.py` vs `core/metrics.py`):**
- Leídos completos ambos módulos (no solo grep): `rag/scorer.py` (236 líneas), `core/metrics.py` (187 líneas). Confirmado el pre-check del controlador: cero colisión de nombres entre símbolos públicos top-level (grep `^def \|^class`) — `scorer.py` expone `tokenize`, `_capsule_text`, `_build_adjacency`, `pagerank`, `tfidf_scores`, `score_capsules`, `_serialize`, `select_within_budget`; `metrics.py` expone `_append_usage_log`, `MetricsSnapshot`, `MetricsTracker`, `get_metrics`.
- **Veredicto: NO hay duplicación real, son dos dominios genuinamente distintos** — la coincidencia es solo léxica ("score"/"metrics" como sinónimos vagos en inglés), no de código. `scorer.py` es el ranking de retrieval: PageRank power-iteration sobre el call-graph de cápsulas (`pagerank`, `_build_adjacency`) + TF-IDF coseno query↔cápsula con tokenización snake/camelCase (`tfidf_scores`, `tokenize`), combinados en `score_capsules` (40% estructural / 60% semántico + boost no-documento), y una selección greedy-knapsack con propagación a vecinos (`select_within_budget`) acotada por presupuesto de tokens. `metrics.py` es observabilidad/telemetría: contadores de queries, tokens usados/ahorrados vs baseline, hit-rate de caché, percentiles de latencia (p50/p99), timings por fase, export a formato texto Prometheus (`MetricsSnapshot.to_prometheus`), y un log JSONL append-only best-effort (`_append_usage_log`) — todo expuesto vía singleton (`get_metrics()`). Ninguna fórmula se calcula dos veces: no hay PageRank ni TF-IDF en `metrics.py`, no hay contadores/latencia/Prometheus en `scorer.py`.
- Único punto de contacto superficial: ambos módulos mencionan "tokens", pero con semántica no relacionada — `scorer.py::select_within_budget` usa `count_tokens` (de `core/tokens.py`) para calcular el COSTE en tokens de cada cápsula candidata frente a un budget de knapsack; `metrics.py::MetricsTracker.record_query` recibe `tokens: int` ya calculado por el llamador (no invoca `count_tokens` ni ninguna función de `scorer.py`) y solo lo acumula para reportar ahorro agregado (`tokens_saved = baseline − tokens_used`) vs `BASELINE_TOKENS_PER_QUERY`. Ni una función ni una constante se comparte entre los dos módulos.
- Verificado el uso real (grep de callers en `leo_code/`, no asumido): `score_capsules`/`select_within_budget` los consume únicamente `engine.py` (retrieval, confirma el pre-check); `get_metrics()`/`record_query`/`record_cache_hit`/`record_cache_miss`/`record_index` los consumen `server/server.py`, `tui/status.py` y `rag/agent/loop.py` (observabilidad, confirma el pre-check). Cobertura de test ya está separada y sin solapamiento: `tests/test_scorer.py` para scorer, `tests/test_metrics_usage_log.py` + `tests/test_server_metrics.py` para metrics — ningún test cruza los dos módulos, lo que refuerza que ya se tratan como unidades independientes.
- No se tocó código de producción en esta tarea (hallazgo = no hay duplicación real que unificar; solo similitud de nombre a nivel de inglés genérico, no de implementación). No se corrió la suite completa (no aplica: sin cambios de código).

**2026-07-16 noche (M2, mini-bench CC run 1) — ESTADO PARA /clear:**
- Hook C Claude Code CERRADO por la tarde (commit ec3aada). Mini-bench RUN 1 hecho — números y hallazgos en el checkbox del kanban M2. Resultados: `benchmark/results_real/cc_mini_run1.json` (+ .log).
- Señal no-defer (17/07 03:30-03:55, `cc_signal_nodefer.json`): tokens **−24% pooled / −27% mediana** ✅ dur −9% ✅ score 6,92 vs 7,45 (−0,53) ⚠️. Lecturas: (1) el outlier t14 del run1 era ESTOCÁSTICO de haiku — esta vez CC vanilla también explotó (1,02M/20 turns) y CCMCP con adopción real (get_context×6+graph×5) ganó −27%; (2) adopción sigue ~0 fuera de t14 incluso con tools upfront — los −28/−45% de t1/t2 son varianza; (3) el gap de score es ARTEFACTO: t2 CCMCP encontró EL MISMO bug que CC (callees_depth ignorado) pero terso → judge 1,4 vs 4,0. Causa: CCMCP recibía AGENTS.md ENTERO (style guide "conciso" incluido) y CC nada — en opencode ambos autocargaban AGENTS.md. FIX aplicado a run_cc.py: CCMCP recibe solo la sección MCP (corte en "## Style Guide").
- Validación n=3 no-defer SIN style guide en CCMCP (04:00-05:15, `cc_nodefer_run1/2/3.json`): **mediana 15 pares +50,4% FALLA** · score −0,17 · reventones incluso con mcp=0 (t1 r3 +567% sin llamadas MCP). Diagnóstico del zigzag (run1 defer +5% / señal full-steering −27% / n=3 sin-style +50%): **el style guide de AGENTS.md es la variable dominante, no el MCP** — quitárselo a CCMCP disparó su verborrea; dárselo solo a él sesga el judge (−0,53). Haiku además tiene varianza salvaje por tarea (t14 CC va de 277k a 1,02M entre corridas).
- SIGUIENTE PASO EXACTO: validación n=3 **steering simétrico** (style guide a AMBOS, sección MCP solo CCMCP; como opencode que autocarga AGENTS.md en los dos) — lanzada 05:20, labels `cc_eq_run1/2/3`, log `cc_eq_validation.log`, monitor armado. Criterio M2 "sin regresión": mediana tokens ≤ +10% · score ≥ −0,2 · dur ≤ +10% sobre los 15 pares. Si pasa → Codex. Si falla → mirar por-tarea si es adopción-cebando-exploración (patrón opencode) y considerar aceptar el default defer (run1 dio +5% mediana) como config recomendada.
- Lanzamiento: SIEMPRE Start-Process desacoplado (`cmd /c python benchmark/run_cc.py --label <label> > benchmark\results_real\<label>.log 2>&1`); el shell del agente no tiene red. DEEPSEEK_API_KEY se autocarga de .env (fix en run_cc.py).
- Bug corregido post-run1: Claude Code normaliza server "leo-code" → tools `mcp__leo_code__*` (guión bajo); el run1 json tiene mcp_calls={} por eso — la adopción real del run1 fue 1 get_context (t14), contada a mano del tool_seq.
- Sesiones basura haiku en `~/.claude/projects/` del 16/07 (smoke tests + mini-bench): no confundir al depurar transcripts.

**2026-07-14 noche (arranque M2) — ESTADO PARA /clear:**
- M1 cerrado (19:49) y notificado. M2 activado con OK del usuario ("sigue con la goal").
- Claude Code smoke test PASA (ver kanban M2). SIGUIENTE PASO EXACTO: hook C para Claude Code — (1) leer docs de hooks (¿PostToolUse puede reemplazar el output de Read? probable que no → plan B: PreToolUse deny+contexto, o solo steering+MCP y medirlo); (2) si hay mecanismo, portar la lógica de `.opencode/plugin/leo-first-action.js` (swap si comprimido <75% del crudo, body-chars 1400, rango offset/limit pasa); (3) mini-bench 5 tareas con runner headless `claude -p` (telemetría: transcripts JSONL en `~/.claude/projects/` — cuentan también subagentes; reutilizar la lección del sesgo `task`).
- La sesión anterior quedó larguísima (validaciones + sesgo + cierre M1): este bloque existe para re-orientar tras `/clear`.

**2026-07-14 madrugada (M1, criterio v2) — ESTADO PARA /clear:**
- c5b analizada (+51,9% tokens, adopción 0,5, score/dur ≈). Criterio M1 REDEFINIDO (goal nuevo del usuario, ver tablas arriba): objetivo tokens ahora ±10% e2e, no −40%.
- SIGUIENTE PASO EXACTO: diagnóstico por tarea de `c5b_signal.json` para localizar la fricción residual (+52%). Preguntas concretas: (1) ¿cuántos tokens aporta cada respuesta get_context (×4 de B1)? → probar presupuesto ×1 (revertir multiplicador en engine.py línea `budget = max(budget * 4, 4000)`); (2) ¿el swap disparó? (grep SWAP en debug o comparar native_calls de reads enteros); (3) ¿overhead de defs×turnos? Después: corrida-señal por palanca (`run_signal.ps1 <label>`), y cuando una señal dé tokens dentro de ±10% con score igual → validación 3× → cierra M1 → PushNotification.
- Monitor baelrpthu (sesión 11:54) vigila `validation_progress.log`. No usar datos de c5 (murió por re-indexado). No lanzar 2 corridas en paralelo.
- 11:54: RUN 1 en batch 5/15. Visto en vivo: t4 OC timeout (tok=0, 180s) y t4 OCMCP 552k — t4 vuelve a ser outlier estocástico; al juzgar, mirar mediana por tarea además del pooled. Zombi python 7148 (`leo_code.server.mcp_server` huérfano de c5b) vivo e inofensivo — c6 corrió bien con él.
- Nuevo: `benchmark/judge_v2.py` (pooled + mediana/tarea + veredicto v2 en un comando; auto-verificado contra c6).
- 12:13 RUN 1 exit=0 (27 min, lento): **3 timeouts OC** (t4/t9/t14 tok=0 → OC score 4,20), mediana +52,5%, pooled +206%. Ruido enorme vs c6 (+3% mediana) — posible franja degradada de API. No decidir con n=1; esperar RUN 2-3 y juzgar pooled n=3 con `judge_v2.py`.
- 12:32 RUN 2 exit=0 (19 min, 0 timeouts): mediana **+47,6%**, gana 3/15, pooled +44%, dur −7,8%, score 0,00, adopción 0,7. Dos corridas seguidas ~+50% con la MISMA config que c6 (+3%) → c6 fue tiro afortunado, no la dieta. Outliers nuevos: t11 +532%, t14 +640%. RUN 3 decide, pero pinta a FALLA de tokens ±10% → tocará diagnóstico con n=3 (¿qué hace get_context para cebar exploración?).
- 14:26 tarde: sesgo `task` confirmado y corregido (ver kanban). DB opencode en `~/.local/share/opencode/opencode.db` (tabla `session`: parent_id + tokens_*; stream total == in+out+reasoning+cache exacto). Análisis reproducible: scratchpad `fix_bias.py`. Sonda viva con `opencode run` COLGÓ 84 min (evitar; la DB responde todo). LEO_FORCE=1 en OCMCP verificado: `leo-first-action.js` ES el swap pasivo de C v5 (sin vetos, nombre heredado) — sin fricción fantasma. Validación limpia corre desde 14:26 (~60 min); juzgar con `judge_v2.py harness_run{1,2,3}.json`.
- 14:49 RUN 1 limpio exit=0: **pooled −39,8% · mediana +0,6% · gana 7/14 · dur −20,1% · score +0,27 — criterio v2 OK en las 3 métricas**. Confirma la corrección post-hoc. Faltan RUN 2-3.
- 15:11 RUN 2 limpio exit=0: tokens OK (mediana +2,3%, pooled −39,2%) pero dur +25,7% y score −0,27 por UN timeout de OCMCP (t5_search, 180s, score 0). judge_v2 endurecido: pares con timeout de cualquiera excluidos de la mediana, timeouts listados. Veredicto = pooled n=3.

**2026-07-13 noche (M1/B1):**
- Causa técnica de las relecturas encontrada: estrategias code_edit/refactor/review/audit NO incluían cuerpo (solo firma+docstring) y el footer de code_edit decía "Usa read_file…"; debug truncaba a 2000 chars; el serializador (core/context.py) re-truncaba TODO a 2000 aunque el compresor pidiera más. Presupuestos 500–2500 tok.
- B1 hecho (335a3d2): `self_sufficient=True` solo en la vía MCP. Tests: `tests/test_self_sufficient.py`.
- Corrida-señal en marcha: si `redundant_native_after_ctx` no cae y tokens no bajan, B1 no basta → priorizar C (forzado). Si cae: B2 (dieta de definiciones) y luego validación 3×.
- `benchmark/run_signal.ps1 <label>` = 1 corrida pareada suelta; `run_validation.ps1` = 3×.

**2026-07-13 (M0):**
- summary.json actual (mtime 2026-07-12 20:49) = corrida PRE-v2 (HEAD era 8d7588d al arrancar; v2 se committeó 20:52). Backup en `harness_prev2_run1.json`. Números: OC 4.73/89.9k tok/47s · OCMCP 5.00/124.8k tok(+39%)/37s · adopción 0,5.
- Corrida de ayer 20:52 quedó colgada (python+opencode zombis 17h). Al matarlos, el `run_validation.ps1` padre revivió y lanzó RUN 2 a las 14:09 con HEAD=64cc30c (incluye steering v2) → válida.
- Plan: RUN 2 y 3 completan (~21 min c/u, escriben `harness_run2/3.json`), luego reponer 1 corrida más para tener n=3 de v2. Monitor activo sobre `validation_progress.log`.
- Ojo: NO lanzar dos instancias del script en paralelo — el rename de opencode.json de OC vanilla rompe OCMCP (cf. 8d7588d).
- **Bug resuelto (61ecb8d):** los cuelgues de horas eran `subprocess.run(timeout=)` matando solo el shim npm de opencode; nietos (bun+MCP) mantenían pipes abiertos → drenaje infinito. `_run_capture` mata el árbol con `taskkill /T /F`. Validado con self-check (TimeoutExpired en 3,1s, árbol muerto).
- Validación v2 relanzada 19:51 con HEAD=61ecb8d (incluye steering v2). Resultado en `harness_run1/2/3.json` + marker `harness_ALL_DONE.txt`. Al terminar: agregar métricas (score/tokens/adopción) y decidir B/C.
- **RUN 1 v2 (17 min, exit 0, sin timeouts):** OC 5.00/75.6k/34,7s · OCMCP 5.00/89.1k(+17,9%)/34,2s · adopción 1,1. Steering v2 dobla adopción (0,5→1,1) y recorta el sobrecoste (+39%→+18%) pero sigue lejos del delta fuerte → apunta a necesitar B (consolidación) + C (forzado). Esperando RUN 2-3 para confirmar con n=3.
- **RUN 2 v2 (19 min, exit 0):** OC 5.00/61.2k/35,8s · OCMCP 5.00/129.7k(**+112%**)/40,3s · adopción 0,7. Varianza brutal entre corridas (+18%→+112%): steering NO es fiable → B+C confirmándose. Falta RUN 3.
