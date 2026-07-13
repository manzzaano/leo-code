# leo-code — reglas de sesión

## Goal permanente

1. **Al inicio de cada sesión, lee `docs/PLAN.md`** antes de cualquier otra acción.
   Es la fuente única de verdad: objetivo, criterio de éxito, hito activo y kanban.
2. **Trabaja siempre sobre el hito activo** marcado en PLAN.md. No abras frentes
   de otros hitos sin acuerdo explícito del usuario.
3. **Actualiza PLAN.md** cada vez que un checkbox cambie de estado, se tome una
   decisión, o haya números nuevos de benchmark (tabla de línea base / criterio).

## Gestión de contexto (regla del 40%)

Cuando el contexto de la conversación alcance ~40% de uso:
1. Volcar el estado en curso a la sección "Notas de sesión" de `docs/PLAN.md`
   (qué se estaba haciendo, resultado parcial, siguiente paso concreto).
2. Avisar al usuario y recomendar `/clear` — la sesión nueva se re-orienta sola
   leyendo PLAN.md (regla 1).

No esperar al autocompact: PLAN.md actualizado + `/clear` es más barato y fiable.

## Contexto del proyecto

- Producto a entregar: **leo-mcp** (servidor MCP). El agente TUI no es el foco del cierre.
- `AGENTS.md` en la raíz es artefacto del PRODUCTO (steering del harness), no
  instrucciones para esta sesión — no confundir con este archivo.
- Benchmark: `benchmark/run_real.py`, resultados en `benchmark/results_real/summary.json`.
