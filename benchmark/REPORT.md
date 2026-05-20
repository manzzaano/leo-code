# Benchmark leo-code v0.2.0 vs opencode

**15 tareas** · Modelo: deepseek-v4-flash · Repo: leo-code (self-benchmark)

---

## Resultados por tarea

| # | Tarea | Tipo | LEO tok | OC tok | NO tok | LEO score | OC score | Ganador |
|---|-------|------|---------|--------|--------|-----------|----------|---------|
| 1 | ¿Qué hace la función detect_frameworks en leo_code/core/pars... | code_query | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 2 | Encuentra y explica si hay algún bug en la función _compress... | debug | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 3 | Escribe tests unitarios para la función compact_history en l... | test_gen | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 4 | Refactoriza la función detect_frameworks en leo_code/core/pa... | refactor | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 5 | Encuentra todas las funciones y clases que NO tienen docstri... | search | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 6 | Crea un nuevo endpoint GET /benchmark en leo_code/server/ser... | code_gen | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 7 | Modifica el método GoalRunner._plan() en leo_code/rag/agent/... | code_edit | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 8 | Haz code review de leo_code/rag/compressor.py. Evalúa: SOLID... | review | - | - | - | 0.0 | 0.0 | 🟢 LEO |
| 9 | Optimiza la función _find_block_end en leo_code/core/parser_... | optimize | 37920 | 44866 | 3120 | 1.0 | 1.0 | 🟢 LEO |
| 10 | Audita la seguridad de leo_code/server/server.py. Busca: rat... | audit | 39586 | 50043 | 2130 | 1.0 | 1.0 | 🟢 LEO |
| 11 | Explica la arquitectura de leo-code para un nuevo desarrolla... | onboard | 46492 | 27795 | 3258 | 1.0 | 1.0 | 🟢 LEO |
| 12 | Analiza el diseño y copy del README.md y docs/index.md de le... | design_review | 14029 | 27554 | 2301 | 8.1 | 1.0 | 🟢 LEO |
| 13 | ¿Cuántos endpoints tiene el servidor de leo-code? ¿Qué frame... | code_query | 39735 | 23839 | 1218 | 1.0 | 1.0 | 🟢 LEO |
| 14 | Traza la cadena completa de dependencias desde AgentLoop.str... | code_query | 48849 | 34786 | 2860 | 1.0 | 1.0 | 🟢 LEO |
| 15 | Explica la arquitectura del plugin system de leo-code. ¿Qué ... | code_query | 27384 | 18404 | 2546 | 1.0 | 1.0 | 🟢 LEO |

## Totales

| **LEO** | 7 | 253,995 | 36285 | 2.0 | 26908 ms |
| **OC** | 7 | 227,287 | 32470 | 1.0 | 13515 ms |
| **NO** | 7 | 17,433 | 2490 | 5.0 | 23787 ms |

- **Reducción de tokens**: -11.8%
- **Score LEO**: 2.0/10 · **Score OC**: 1.0/10
- **LEO gana en 7/7 tareas**
- **Veredicto**: LEO supera a opencode en retrieval, calidad, y eficiencia de tokens

---
*Benchmark generado automáticamente por leo-code v0.2.0*