# PLAN — Cierre de leo-code (fuente única de verdad)

> **Regla de trabajo:** este archivo se lee al inicio de CADA sesión y se actualiza
> ANTES de cerrar contexto. Si el contexto de la conversación supera ~40%, volcar
> estado aquí y pedir `/clear`.

**Última actualización:** 2026-07-13 20:55 · **Hito activo: M1**

## Objetivo

Entregar **leo-mcp** (servidor MCP, 6 tools) empaquetado a compañeros para que lo
usen en su agente diario y den su visto bueno. "Terminado" = cumple sus promesas
con **delta fuerte** medido vs agente vanilla.

### Criterio de éxito (delta fuerte, OC+leo-mcp vs OC vanilla, benchmark 15 tareas × 3 corridas)

| Métrica | Umbral |
|---|---|
| Tokens | **≥40% menos** |
| Score respuesta | **+0.5** |
| Duración | **−30%** |
| Adopción | ≥2 llamadas MCP/tarea estructural |

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
- [ ] **B1 — get_context autosuficiente:** incluir cuerpos fuente relevantes en la respuesta (con cap de tokens) para que el agente NO relea archivos. Métrica guía: `redundant_native_after_ctx` → ~0 (hoy: hasta 15 relecturas/tarea).
- [ ] **B2 — dieta de definiciones:** revisar tamaño/número de tools expuestas (uso real: get_context 31, where 7, trace 4, resto 0 en 45 tareas). Fusionar o adelgazar lo no usado sin romper la promesa del producto.
- [ ] **C — primera acción forzada (opencode):** plugin/config que garantice `get_context` como primer paso en tareas de código. Métrica guía: adopción ≥2 en tareas estructurales, varianza entre corridas ↓.
- [ ] Benchmark 15 tareas × 3 corridas tras B1+B2, y otra tras C
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

## Notas de sesión

**2026-07-13 (M0):**
- summary.json actual (mtime 2026-07-12 20:49) = corrida PRE-v2 (HEAD era 8d7588d al arrancar; v2 se committeó 20:52). Backup en `harness_prev2_run1.json`. Números: OC 4.73/89.9k tok/47s · OCMCP 5.00/124.8k tok(+39%)/37s · adopción 0,5.
- Corrida de ayer 20:52 quedó colgada (python+opencode zombis 17h). Al matarlos, el `run_validation.ps1` padre revivió y lanzó RUN 2 a las 14:09 con HEAD=64cc30c (incluye steering v2) → válida.
- Plan: RUN 2 y 3 completan (~21 min c/u, escriben `harness_run2/3.json`), luego reponer 1 corrida más para tener n=3 de v2. Monitor activo sobre `validation_progress.log`.
- Ojo: NO lanzar dos instancias del script en paralelo — el rename de opencode.json de OC vanilla rompe OCMCP (cf. 8d7588d).
- **Bug resuelto (61ecb8d):** los cuelgues de horas eran `subprocess.run(timeout=)` matando solo el shim npm de opencode; nietos (bun+MCP) mantenían pipes abiertos → drenaje infinito. `_run_capture` mata el árbol con `taskkill /T /F`. Validado con self-check (TimeoutExpired en 3,1s, árbol muerto).
- Validación v2 relanzada 19:51 con HEAD=61ecb8d (incluye steering v2). Resultado en `harness_run1/2/3.json` + marker `harness_ALL_DONE.txt`. Al terminar: agregar métricas (score/tokens/adopción) y decidir B/C.
- **RUN 1 v2 (17 min, exit 0, sin timeouts):** OC 5.00/75.6k/34,7s · OCMCP 5.00/89.1k(+17,9%)/34,2s · adopción 1,1. Steering v2 dobla adopción (0,5→1,1) y recorta el sobrecoste (+39%→+18%) pero sigue lejos del delta fuerte → apunta a necesitar B (consolidación) + C (forzado). Esperando RUN 2-3 para confirmar con n=3.
- **RUN 2 v2 (19 min, exit 0):** OC 5.00/61.2k/35,8s · OCMCP 5.00/129.7k(**+112%**)/40,3s · adopción 0,7. Varianza brutal entre corridas (+18%→+112%): steering NO es fiable → B+C confirmándose. Falta RUN 3.
