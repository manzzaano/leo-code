# Benchmark leo-code vs opencode — REPORT FINAL

**Fecha:** 2026-05-21 03:40  
**Ejecuciones:** 44  
**Modelos:** DeepSeek V3, R1, V4 Flash, V4 Pro  
**Modos:** LEO-RAG, LEO-AGT, OC  

---

## Tabla comparativa

| Modelo | Modo | Score | Tokens | Tiempo |
|--------|------|------:|-------:|-------:|
| deepseek-chat | LEO-RAG | 8.8 | 7272 | 43s |
| deepseek-chat | LEO-AGT | 2.2 | 0 | 38s |
| deepseek-chat | OC | 8.2 | 887 | 18s |
| deepseek-reasoner | LEO-RAG | 8.7 | 7617 | 37s |
| deepseek-reasoner | OC | 8.6 | 1022 | 47s |
| deepseek-v4-flash | LEO-RAG | 8.9 | 8393 | 41s |
| deepseek-v4-flash | LEO-AGT | 8.7 | 6220 | 44s |
| deepseek-v4-flash | OC | 8.6 | 807 | 44s |
| deepseek-v4-pro | LEO-RAG | 8.4 | 8942 | 139s |
| deepseek-v4-pro | LEO-AGT | 8.7 | 6624 | 167s |
| deepseek-v4-pro | OC | 8.4 | 1493 | 162s |

---

## Detalle por tarea

### t1_code_query

| Sistema | Score | Tokens | Tiempo |
|---------|------:|-------:|-------:|
| deepseek-chat:rag | 9.0 | 6838 | 68s |
| deepseek-v4-flash:rag | 8.8 | 9650 | 59s |
| deepseek-v4-pro:oc | 8.8 | 262 | 62s |
| deepseek-v4-flash:agent | 8.7 | 7680 | 41s |
| deepseek-reasoner:rag | 8.1 | 7173 | 43s |
| deepseek-reasoner:oc | 8.1 | 988 | 18s |
| deepseek-v4-pro:agent | 8.1 | 7898 | 108s |
| deepseek-v4-flash:oc | 7.3 | 802 | 15s |
| deepseek-chat:oc | 7.2 | 695 | 13s |
| deepseek-v4-pro:rag | 7.2 | 9434 | 152s |
| deepseek-chat:agent | 0.0 | 0 | 37s |

### t8_review

| Sistema | Score | Tokens | Tiempo |
|---------|------:|-------:|-------:|
| deepseek-chat:rag | 8.9 | 8468 | 30s |
| deepseek-reasoner:rag | 8.9 | 9257 | 36s |
| deepseek-reasoner:oc | 8.9 | 846 | 34s |
| deepseek-v4-flash:rag | 8.9 | 9006 | 28s |
| deepseek-v4-flash:oc | 8.9 | 676 | 33s |
| deepseek-v4-pro:rag | 8.9 | 9454 | 102s |
| deepseek-v4-pro:agent | 8.9 | 9855 | 155s |
| deepseek-chat:oc | 8.8 | 936 | 17s |
| deepseek-v4-flash:agent | 8.7 | 9428 | 43s |
| deepseek-v4-pro:oc | 8.2 | 1797 | 234s |
| deepseek-chat:agent | 0.0 | 0 | 33s |

### t11_onboard

| Sistema | Score | Tokens | Tiempo |
|---------|------:|-------:|-------:|
| deepseek-v4-flash:oc | 9.2 | 796 | 103s |
| deepseek-v4-pro:agent | 9.0 | 8746 | 187s |
| deepseek-reasoner:rag | 8.8 | 7900 | 29s |
| deepseek-chat:rag | 8.8 | 8346 | 35s |
| deepseek-v4-flash:rag | 8.8 | 8494 | 35s |
| deepseek-v4-flash:agent | 8.8 | 7775 | 36s |
| deepseek-v4-pro:rag | 8.8 | 9112 | 122s |
| deepseek-reasoner:oc | 8.6 | 1138 | 103s |
| deepseek-chat:oc | 8.1 | 1040 | 22s |
| deepseek-v4-pro:oc | 8.1 | 2297 | 201s |
| deepseek-chat:agent | 0.0 | 0 | 33s |

### t12_design_review

| Sistema | Score | Tokens | Tiempo |
|---------|------:|-------:|-------:|
| deepseek-reasoner:rag | 9.2 | 6141 | 40s |
| deepseek-v4-flash:rag | 9.2 | 6425 | 44s |
| deepseek-v4-flash:oc | 9.2 | 954 | 25s |
| deepseek-chat:rag | 8.8 | 5439 | 41s |
| deepseek-chat:agent | 8.8 | 0 | 48s |
| deepseek-chat:oc | 8.8 | 880 | 18s |
| deepseek-reasoner:oc | 8.8 | 1116 | 32s |
| deepseek-v4-pro:rag | 8.8 | 7771 | 178s |
| deepseek-v4-pro:oc | 8.8 | 1619 | 153s |
| deepseek-v4-flash:agent | 8.7 | 0 | 55s |
| deepseek-v4-pro:agent | 8.7 | 0 | 218s |

---

## Winners por categoría

- **LEO-RAG mejor modelo:** `deepseek-v4-flash` — 8.9/10
- **LEO-AGT mejor modelo:** `deepseek-chat` — 8.8/10
- **OC mejor modelo:** `deepseek-v4-flash` — 8.6/10