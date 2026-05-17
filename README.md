<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="packages/console/app/src/asset/logo-ornate-dark.svg">
    <img alt="leo/code" src="packages/console/app/src/asset/logo-ornate-dark.svg" width="160">
  </picture>

  <br><br>

  <p>
    <strong>Terminal Agent · Recuperación Estructural de Código</strong><br>
    <sub>El código no es texto. Es un grafo. Tu agente debería tratarlo como tal.</sub>
  </p>

  <p>
    <a href="https://leosoftware.dev/leo-code">
      <img src="https://img.shields.io/badge/Web-leosoftware.dev/leo--code-1d4ed8?style=flat-square&labelColor=070708">
    </a>
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-34d399?style=flat-square&labelColor=070708">
    </a>
    <a href="#kc-rag">
      <img src="https://img.shields.io/badge/KC--RAG-Estructural-5B8DEF?style=flat-square&labelColor=070708">
    </a>
    <a href="#modelos">
      <img src="https://img.shields.io/badge/Modelos-75%2B-1d4ed8?style=flat-square&labelColor=070708">
    </a>
  </p>
</div>

---

## El problema

Todos los agentes de terminal recuperan código igual: **chunking por número de caracteres + similitud coseno de embeddings.**

Esto produce tres fallos estructurales:

| Fallo | Causa | Consecuencia |
|-------|-------|-------------|
| **Cortes a mitad de función** | El chunk de 500 tokens parte `verifyUser()` por la mitad | El LLM ve medio comportamiento |
| **Aislamiento de dependencias** | Recupera `verifyUser` pero no `hashPassword` (la que realmente llama) | El bug está en la dependencia no recuperada |
| **Falsos positivos semánticos** | Trae `verifyEmail` porque "verify" + "user" = "verify" + "email" | Contexto irrelevante, tokens desperdiciados |

**Resultado**: 70-85% del contexto enviado al LLM es ruido. Se paga en tokens y en calidad.

---

## KC-RAG: la solución

**KC-RAG no busca texto similar. Recupera el subgrafo de dependencias.**

```
Código fuente
    ↓ tree-sitter + AST
Cápsulas (función, clase, módulo) con dependencias (LLAMA, IMPORTA, HEREDA)
    ↓ Qdrant HNSW + BFS expansión + cross-encoder rerank
Subgrafo conexo de cápsulas relevantes
    ↓ Compresión adaptativa por tipo de tarea
Contexto estructural (~200-2000 tokens)
```

### Qué mide KC-RAG que otros no miden

| Métrica | Qué significa | KC-RAG | Chunking tradicional |
|---------|--------------|--------|---------------------|
| **Integridad de cápsula** | ¿Se recupera la función completa? | ✅ Nunca se corta | ❌ Cortes a 500 tokens |
| **Conectividad topológica** | ¿Vienen las dependencias? | ✅ BFS depth 2 | ❌ Fragmentos aislados |
| **Grounding determinista** | ¿Se puede trazar cada afirmación a una cápsula? | ✅ Python extrae nombres del texto | ❌ Sin trazabilidad |
| **Presupuesto adaptativo** | ¿El contexto se ajusta al tipo de tarea? | ✅ 200-2000 tokens según tarea | ❌ Tamaño fijo |
| **Cache estructural** | ¿Se reutiliza el grafo entre consultas? | ✅ Redis L1/L2/L3 | ❌ Sin cache |

---

## Instalación

```bash
curl -fsSL https://leosoftware.dev/leo-code/install | bash
```

| Vía | Comando |
|-----|---------|
| npm | `npm i -g leo-code@latest` |
| Python (sidecar) | `pip install leo-code-mcp` |
| Fuente | `git clone https://github.com/manzzaano/leo-code && cd leo-code && bun install` |

---

## Stack

<div align="center">

| Capa | Tecnología | Función |
|------|-----------|---------|
| **Parser** | tree-sitter + AST (Python) | Extraer cápsulas del código fuente |
| **Vector** | Qdrant HNSW | Búsqueda semántica top-50 |
| **Grafo** | BFS + edge expansion | Expandir dependencias (LLAMA, IMPORTA, HEREDA) |
| **Reranker** | BGE cross-encoder | Relevancia conjunta consulta-cápsula |
| **Compresor** | KC-RAG adaptativo | 200-2000 tokens según tipo de tarea |
| **Cache** | Redis L1/L2/L3 | Ontología permanente + subgrafos 300s + queries 60s |
| **Grounding** | Python determinista | Extrae entidades del texto a node_id real |
| **Modelos** | 75+ proveedores | DeepSeek V4, Claude, GPT, Ollama, OpenRouter... |

</div>

---

## Sistema de diseño

<div align="center">

| Token | Valor | Uso |
|-------|-------|-----|
| `--color-bg-base` | `#070708` | Fondo TUI |
| `--color-accent` | `#1d4ed8` | Cobalto — marca |
| `--color-accent-muted` | `#5B8DEF` | Logo "/" |
| `--font-sans` | Space Grotesk | UI |
| `--font-mono` | JetBrains Mono | Código |

</div>

---

## Empezar

```bash
git clone https://github.com/manzzaano/leo-code.git
cd leo-code
bun install && bun run build
leo-code-mcp &    # Sidecar KC-RAG (auto-arrancado por leo-code)
leo-code          # Terminal interactivo
```

| Comando | Descripción |
|---------|------------|
| `leo-code` | Modo interactivo (agente completo) |
| `leo-code "refactor auth"` | Consulta directa con KC-RAG |
| `leo-code index .` | Indexar repo para retrieval estructural |
| `leo-code index . --tree-sitter` | Indexar con tree-sitter multi-lenguaje |

---

## Lo que KC-RAG hace posible

**Antes** (chunking semántico): el LLM recibe 80K tokens de fragmentos de código sueltos. Pasa el 70% del razonamiento filtrando ruido.

**Después** (KC-RAG): el LLM recibe ~2K tokens de un subgrafo conexo de cápsulas relevantes. Dedica el 100% a resolver el problema.

```
Tarea: "refactorizar autenticación para usar async"

SIN KC-RAG:
  Contexto: chunks de verifyUser, verifyEmail, resetPassword, config, 
            middleware, types, utils... (80% ruido)
  Tokens: ~120K

CON KC-RAG:
  Contexto: verifyUser + hashPassword + checkSession + sus imports directos
  Tokens: ~2K
  Grounding: cada afirmación trazable a una cápsula
```

---

<div align="center">
  <br>
  <a href="https://leosoftware.dev/leo-code">
    <img src="https://img.shields.io/badge/leosoftware.dev/leo--code-1d4ed8?style=for-the-badge&labelColor=070708" alt="leo-code">
  </a>
  <br><br>
  <sub>
    Construido por <a href="https://github.com/manzzaano">Ismael Manzano</a> ·
    <a href="https://leosoftware.dev">leosoftware.dev</a> ·
    © 2026 — MIT
  </sub>
</div>
