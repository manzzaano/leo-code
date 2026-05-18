<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="packages/console/app/src/asset/logo-ornate-dark.svg">
    <img alt="leo/code" src="packages/console/app/src/asset/logo-ornate-dark.svg" width="160">
  </picture>

  <br><br>

  <p>
    <strong>Agente de terminal con Recuperación Estructural de Código (KC-RAG)</strong><br>
    <sub>Fork de opencode — el código es un grafo, no texto plano.</sub>
  </p>

  <p>
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-34d399?style=flat-square&labelColor=070708">
    </a>
    <a href="#kc-rag">
      <img src="https://img.shields.io/badge/KC--RAG-Estructural-5B8DEF?style=flat-square&labelColor=070708">
    </a>
    <a href="#benchmark">
      <img src="https://img.shields.io/badge/benchmark-v12-1d4ed8?style=flat-square&labelColor=070708">
    </a>
  </p>
</div>

---

## Qué es esto

**leo-code** es un fork de [opencode](https://github.com/sst/opencode) con un plugin KC-RAG integrado. En lugar de dejar que el agente explore el código libremente (abriendo archivos, buscando en el árbol de directorios), leo-code **inyecta el contexto relevante antes de que el modelo vea la pregunta**.

El sidecar KC-RAG (`leo-code-mcp`) indexa el repositorio, construye un índice vectorial y devuelve las cápsulas de código más relevantes comprimidas, adaptadas al tipo de tarea. El agente responde con ese contexto ya disponible.

---

## El problema del chunking tradicional

Todos los agentes de código actuales recuperan contexto igual: **chunking por longitud + similitud coseno de embeddings.**

| Fallo | Causa | Consecuencia |
|-------|-------|-------------|
| Cortes a mitad de función | El chunk de 500 tokens parte `verifyUser()` | El LLM ve medio comportamiento |
| Dependencias perdidas | Recupera `verifyUser` pero no `hashPassword` (que es la que falla) | El bug está en una función que no llega al contexto |
| Falsos positivos semánticos | `verifyEmail` parece relevante para "verify user" | Contexto irrelevante, tokens desperdiciados |

**Resultado típico**: 70-85% del contexto enviado al LLM es ruido.

---

## KC-RAG: recuperación por subgrafo de dependencias

KC-RAG no busca texto similar. Recupera el **subgrafo de dependencias** de las cápsulas relevantes.

```
Código fuente
    ↓ AST (tree-sitter + Python ast)
Cápsulas: función, clase, módulo — con metadatos (calls, imports, docstring)
    ↓ Índice Qdrant HNSW + match exacto por nombre/archivo
Candidatos relevantes (top 15 semánticos + exact match)
    ↓ Compresión adaptativa por tipo de tarea
Contexto estructural (~400–2000 tokens)
    ↓ Inyectado en el system prompt por plugin.ts
El modelo responde directamente sin abrir archivos
```

### Tipos de tarea y compresión adaptativa

| Tipo | Qué incluye el contexto | Tokens aprox. |
|------|------------------------|---------------|
| `code_query` | Primera cápsula con cuerpo completo + firmas del resto | 500–2000 |
| `refactor` | Función target + todas sus callees + callers | 800–1500 |
| `search` | Mapa de funciones con indicador ✓doc/✗doc | 300–800 |
| `no_code` | Solo cápsulas de tipo documento (tarifas, condiciones) | 100–500 |
| `code_gen` | Estructura de directorios sin cuerpos | 200–600 |

---

## Arquitectura

```
Usuario → leo-code CLI (TypeScript/opencode)
              ↓ plugin.ts intercepta la query
              ↓ POST /context a leo-code-mcp (:9898)
         KC-RAG Sidecar (FastAPI Python)
              ↓ Indexer (AST) → Qdrant → Compressor
              ↓ contexto ~400-2000 tokens
         plugin.ts inyecta en system prompt
              ↓
         Modelo LLM (DeepSeek, Claude, GPT, ...)
              ↓ responde del contexto KC-RAG
         Respuesta al usuario
```

### Componentes

| Componente | Ubicación | Función |
|-----------|-----------|---------|
| `plugin.ts` | `packages/leo-code/src/context/` | Intercepta queries, llama al sidecar, inyecta contexto |
| `kcrag.ts` | `packages/leo-code/src/context/` | Cliente HTTP del sidecar |
| `server.py` | `sidecar/leo_mcp/` | FastAPI: /context, /index, /search, /health |
| `compressor.py` | `kc-rag/kc_code/kc_rag/` | Compresión adaptativa por tipo de tarea |
| `classifier.py` | `kc-rag/kc_code/kc_rag/` | Clasificación automática del tipo de tarea |
| `kc_core/` | `kc-core/kc_core/` | Librería base: Capsule, parser, serialize_context |

---

## Benchmark

Medimos leo-code contra dos baselines en **6 tareas reales sobre el propio código del proyecto**:

- **LEO**: leo-code con KC-RAG integrado (agente completo)
- **OC**: DeepSeek API directa sin herramientas ni contexto (baseline mínimo)
- **KC-API**: DeepSeek API + contexto KC-RAG inyectado, llamada única (sin agente)
- **NO**: DeepSeek API sin contexto ni herramientas

### Resultados v12 (2026-05-18)

| Sistema | Tokens totales | Criterios avg | Judge (6 tareas) |
|---------|---------------|---------------|-----------------|
| **LEO** | 84.148 | 76.2% | 3/6 |
| OC (baseline) | 4.259 | 50.5% | 2/6 |
| **KC-API** | 4.257 | 69.2% | 2/6 |
| NO (sin contexto) | 1.867 | 51.3% | 3/6 |

### Métricas de eficiencia

- **TRR** (Token Reduction Rate): `1 − (tokens_leo / tokens_oc)` — cuánto menos tokens usa LEO vs baseline
- **QPR** (Quality-Per-Resource): `TRR × (criterios_leo / criterios_oc)` — calidad relativa por coste

### Observación clave

El modo **KC-API** (inyección directa de contexto KC-RAG + llamada única al LLM, sin agente) obtiene **69% de criterios a solo 4.257 tokens** — casi igual que LEO (76%) pero a **20x menor coste**. La inyección de contexto funciona; el overhead viene del agente usando herramientas adicionales.

El benchmark se ejecuta con `python benchmark/agent_compare.py` desde `leo-code/benchmark/`.

---

## Instalación (CLI Python)

> Monorepo único — todo está en este repositorio. No se necesita Node/Bun.

```bash
# 1. Clonar leo-code
git clone https://github.com/manzzaano/leo-code.git
cd leo-code

# 2. Instalar el CLI y las librerías en modo editable
pip install -e cli/ -e kc-rag/ -e kc-core/

# 3. Variables de entorno (una o más según el proveedor que uses)
# PowerShell:
$env:DEEPSEEK_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # opcional, solo si usas Claude

# bash/zsh:
# export DEEPSEEK_API_KEY=sk-...
# export ANTHROPIC_API_KEY=sk-ant-...

# 4. Uso inmediato (el sidecar KC-RAG arranca automáticamente)
leo-code ask "Qué hace la función retrieve_subgraph?" --repo /ruta/al/repo
leo-code chat --repo /ruta/al/repo
leo-code index /ruta/al/repo
```

### Comandos disponibles

```
leo-code ask  <pregunta>           Consulta directa al agente
leo-code chat                      Modo conversacional multi-turn
leo-code index <repo>              Indexar repositorio en KC-RAG
leo-code serve                     Arrancar el sidecar KC-RAG manualmente

Opciones comunes:
  --repo   -r  Ruta del repositorio (por defecto: directorio actual)
  --model  -m  Modelo LLM (por defecto: auto-selección por complejidad)
  --no-rag     Desactivar contexto KC-RAG (baseline directo al LLM)
```

### Selección de modelos

| Opción `--model` | Descripción |
|-----------------|-------------|
| `auto` (por defecto) | Auto-selección: DeepSeek Flash para simple, Claude Sonnet para medio/código |
| `deepseek/deepseek-chat` | DeepSeek API — económico, buen rendimiento en código |
| `anthropic/claude-sonnet-4` | Claude Sonnet — mejor para razonamiento complejo |
| `anthropic/claude-opus-4` | Claude Opus — máxima calidad |

---

## Estado actual

| Componente | Estado |
|-----------|--------|
| CLI Python (`leo-code ask/chat/index`) | ✅ Funcional — sin dependencia de opencode |
| Sidecar KC-RAG (:9898) | ✅ Funcional — /context, /index, /search, /health |
| Indexación Python (AST) | ✅ Funcional — extrae cápsulas sin LLM |
| Búsqueda híbrida (exact + semántica) | ✅ Funcional — Qdrant + match por nombre/archivo |
| Compresión adaptativa | ✅ Funcional — 5 tipos de tarea |
| Multi-turn (chat con historial) | ✅ Funcional |
| AnthropicProvider (Claude) | ✅ Implementado — requiere `pip install anthropic` |
| Benchmark | ✅ 6 tareas, 4 sistemas, LLM judge |
| Indexación incremental (watcher) | ❌ Pendiente |
| Publicación PyPI | ❌ Pendiente |

---

## Desarrollo

```bash
# Instalar en modo editable (cambios en código se reflejan sin reinstalar)
pip install -e cli/ -e kc-rag/ -e kc-core/

# Tests
pytest kc-rag/tests/
```

> `packages/` contiene el fork TypeScript experimental de opencode — no está mantenido activamente.

---

<div align="center">
  <sub>
    Construido por <a href="https://github.com/manzzaano">Ismael Manzano</a> ·
    Fork de <a href="https://github.com/sst/opencode">opencode</a> ·
    © 2026 — MIT
  </sub>
</div>
