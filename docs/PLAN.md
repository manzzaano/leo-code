# PLAN — Cierre de leo-code (fuente única de verdad)

> **Regla de trabajo:** este archivo se lee al inicio de CADA sesión y se actualiza
> ANTES de cerrar contexto. Si el contexto de la conversación supera ~40%, volcar
> estado aquí y pedir `/clear`.

**Última actualización:** 2026-07-14 14:30 · **Hito activo: M1**

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
| Corrección estructural (graph: impact/trace/guard/who_calls) | 100% precisión+recall vs oráculos, gateado en CI | ✅ ya probado (`audit_formal.py`) |
| Ahorro POR consulta (get_context vs leer los archivos que cubre) | 80-97% | ✅ ya probado (`token_efficiency.py`) |
| Calidad (score juez, 3× validación) | OCMCP ≥ OC | por validar |
| Velocidad | duración ≤ +10% vs vanilla | por validar |
| Sobrecoste tokens e2e | **dentro de ±10%** vs vanilla (hoy +52%: eliminar fricción residual) | **TRABAJO PENDIENTE** |

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

### 🔵 M1 — Delta fuerte en opencode (ACTIVO)
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
- [~] **Palanca anti-timeout/fricción**: los timeouts de OCMCP cayeron en sus tareas de fricción (t5, t4). Fricción sistemática restante = tareas que exigen texto exacto: t2_debug +224%, t4_refactor +103%, t7_code_edit +62% — el swap (body-chars 600) da vista comprimida y el agente compensa releyendo/grepeando. Cambio mínimo: subir body-chars del swap → señal → si t2/t4/t7 caen sin nueva fricción → validación 3× → cierre.
- Diagnóstico fricción restante (read-only, clean n=3): **t2_debug** = OCMCP hace 2-4 reads + 2-3 greps sin MCP (113→188k) vs 1 read de OC — hipótesis: el swap (body-chars 600) recorta el detalle que depurar exige → exploración compensatoria; palanca: subir body-chars del swap o swap solo para archivos grandes. **t5_search** = OC usa bash barato; OCMCP se dispersa (get_context+write / timeout / task 584k) — palanca: steering no debe desincentivar bash para búsquedas. NO tocar hasta cerrar n=6.
- [x] **B2 — dieta de definiciones** (commit 381803e): descripciones 823→664 tok/turno (−19%). Marginal; la palanca es C.
- [x] **C — primera acción forzada (opencode)** (commit 5bc375f): plugin `.opencode/plugin/leo-first-action.js` veta read/grep/glob/list hasta la 1ª llamada a get_context; válvula tras 3 vetos; gated LEO_FORCE=1 (benchmark lo activa solo en OCMCP). Validado: smoke test + 4 ramas en node.
- [ ] Benchmark 15 tareas × 3 corridas con B1+B2+C (HEAD≥5bc375f) → tabla de criterio
- **Done cuando:** tabla de criterio de éxito cumple los 4 umbrales

### ⚪ M2 — Multi-harness
- [ ] Claude Code: instalación + hook C + smoke test + mini-benchmark (5 tareas)
- [ ] Codex: instalación + smoke test + mini-benchmark (5 tareas)
- **Done cuando:** los 3 harnesses instalan y pasan smoke test; mini-bench sin regresión

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

## Notas de sesión

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
