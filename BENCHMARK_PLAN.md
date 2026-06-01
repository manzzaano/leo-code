# Benchmark leo-code vs opencode — Plan de ejecución

**Versión**: 1.0 · **Fecha**: 2026-05-20 · **Autor**: leo-code team

---

## Objetivo

Comparar **leo-code v0.2.0** vs **opencode** (CLI real) usando los 4 modelos DeepSeek disponibles. Medir **tiempo real**, **tokens consumidos** y **calidad de respuesta** (LLM Judge).

---

## Metodología

- **Sin wrappers, sin simulaciones.** Ambos CLIs reales como subprocesos independientes.
- **Mismas queries, mismo repo, mismo modelo.**
- Ejecución limpia: sin indexer output en stdout, sin ANSI codes en opencode.
- Judge doble ciego post-ejecución (no sabe qué sistema generó la respuesta).
- Resultados guardados en `benchmark/results_final/` + reporte `benchmark/REPORT_FINAL.md`.

---

## Modelos (4 DeepSeek)

| # | Modelo | ID | Costo $/1M tok | Thinking |
|---|--------|----|:---:|:---:|
| 1 | DeepSeek V3 | `deepseek/deepseek-chat` | $0.29/$0.43 | No |
| 2 | DeepSeek R1 | `deepseek/deepseek-reasoner` | $0.55/$2.19 | Sí |
| 3 | DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` | $0.14/$0.28 | Sí |
| 4 | DeepSeek V4 Pro | `deepseek/deepseek-v4-pro` | $1.74/$3.48 | Sí |

---

## Configuraciones a probar

| Código | Sistema | Descripción |
|--------|---------|-------------|
| `LEO-RAG` | leo-code RAG directo | KC-RAG inyecta contexto → LLM responde SIN tools. Ideal para modelos con tool calling débil. |
| `LEO-AGT` | leo-code Agente | AgentLoop con tools + KC-RAG. Para modelos que soporten multi-turn tool calling. |
| `OC` | opencode CLI | `opencode run "query" -m MODEL`. Sin KC-RAG, explora con tools. Baseline real. |

---

## Matriz de ejecución

| Modelo | LEO-RAG | LEO-AGT | OC |
|--------|:---:|:---:|:---:|
| V3 (deepseek-chat) | ✅ | ✅ | ✅ |
| R1 (deepseek-reasoner) | ✅ | — | ✅ |
| V4 Flash | ✅ | ✅ | ✅ |
| V4 Pro | ✅ | ✅ | ✅ |

**Total: 10 configuraciones × 4 tareas = 40 ejecuciones. Tiempo estimado: ~30 min.**

---

## Tareas (4)

| # | ID | Tipo | Query |
|---|----|------|-------|
| 1 | `t1_code_query` | code_query | "Qué hace la función detect_frameworks en leo_code/core/parser.py? Dame la lista completa de frameworks que detecta." |
| 2 | `t8_review` | review | "Haz code review de leo_code/rag/compressor.py. Evalúa SOLID, naming, complejidad, manejo de errores. Da 3 recomendaciones concretas." |
| 3 | `t11_onboard` | onboard | "Explica la arquitectura de leo-code para un nuevo desarrollador: estructura de directorios, entrypoints, flujo de una query, módulos principales." |
| 4 | `t12_design_review` | design_review | "Analiza el diseño y copy del README.md y docs/index.md de leo-code. Sugiere mejoras concretas de claridad, persuasión y estructura." |

---

## Métricas

| Métrica | Cómo se mide | Fuente |
|---------|-------------|--------|
| **Tiempo** | `time.time()` entre inicio y fin del subproceso | `subprocess.run` |
| **Tokens** | `response.usage.input_tokens + output_tokens` del LLM | API response |
| **Score** | LLM Judge evalúa 4 dimensiones (1-10): relevancia, corrección, completitud, accionabilidad | `benchmark/judge.py` |
| **Score compuesto** | `relevancia*0.30 + correccion*0.30 + completitud*0.25 + accionabilidad*0.15` | `score_summary()` |

---

## Correcciones técnicas respecto a intentos anteriores

| Problema | Causa | Solución |
|----------|-------|----------|
| opencode devolvía 0 chars | `text=True` usa cp1252 en Windows, falla con UTF-8 | `encoding="utf-8", errors="replace"` |
| Indexer contaminaba stdout de leo-code | `sys.stdout` del subproceso captura `print()` del indexer | Escribir resultado en stderr con marcador `__LEO_RESULT__` |
| Judge fallaba en nested event loop | `judge()` llamaba `asyncio.run()` dentro de otro loop | Ejecutar judge en `ThreadPoolExecutor` con nuevo event loop |
| Agent mode no completaba respuestas | DeepSeek V3 se enreda en tool calling multi-turn | Modo `rag_direct()` sin tools para modelos débiles |

---

## Ejecución

```powershell
cd C:\Users\Ismael\Desktop\leo-code
$env:DEEPSEEK_API_KEY = "sk-..."
python benchmark/benchmark_final.py
```

---

## Resultado

- **JSON**: `benchmark/results_final/summary.json`
- **Markdown**: `benchmark/REPORT_FINAL.md`
- **Consola**: tabla comparativa al final de la ejecución
