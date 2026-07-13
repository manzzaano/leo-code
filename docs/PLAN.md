# PLAN — Cierre de leo-code (fuente única de verdad)

> **Regla de trabajo:** este archivo se lee al inicio de CADA sesión y se actualiza
> ANTES de cerrar contexto. Si el contexto de la conversación supera ~40%, volcar
> estado aquí y pedir `/clear`.

**Última actualización:** 2026-07-13 · **Hito activo: M0**

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

## Estrategia acordada

**B + C, con A solo como remate:**

- **B — Menos tools, más ricas:** consolidar tools (`get_context` devuelve subgrafo+fuente+impacto en una llamada), recortar overhead de definiciones, respuesta autosuficiente (sin re-lecturas de archivos).
- **C — Adopción forzada por harness:** hook Claude Code (UserPromptSubmit inyecta contexto), plugin/config opencode, equivalente Codex. Adopción determinista, no persuadida.
- **A — Steering iterativo:** solo ajustes finales; ya no es la vía principal.

Harnesses objetivo: **Claude Code, opencode, Codex**. Sin fecha límite: kanban por hitos.

## Kanban

### 🔵 M0 — Diagnóstico (ACTIVO)
- [ ] Corrida de validación de steering v2 (commit e3e9f0f, sin validar)
- [ ] Analizar: ¿adopción sube? ¿tokens bajan? → decide cuánto B/C hace falta
- **Done cuando:** hay números de steering v2 y decisión B/C documentada aquí

### ⚪ M1 — Delta fuerte en opencode
- [ ] Implementar B (consolidación de tools según diagnóstico M0)
- [ ] Implementar C para opencode si B no basta
- [ ] Benchmark 15 tareas × 3 corridas
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

## Notas de sesión

_(volcar aquí estado en curso antes de /clear)_
