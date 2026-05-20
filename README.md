# leo-code

**KC-RAG — Knowledge Capsule Retrieval-Augmented Generation para código.**

Recuperación estructural de código por subgrafo de dependencias. En lugar de chunking por longitud + similitud coseno de embeddings (como hacen todos los agentes actuales), KC-RAG extrae cápsulas del AST, las indexa en Qdrant, y devuelve el subgrafo de dependencias relevante comprimido según el tipo de tarea.

---

## El problema del chunking tradicional

| Fallo | Causa | Consecuencia |
|-------|-------|-------------|
| Cortes a mitad de función | El chunk de 500 tokens parte `verifyUser()` | El LLM ve medio comportamiento |
| Dependencias perdidas | Recupera `verifyUser` pero no `hashPassword` (que es la que falla) | El bug está en una función que no llega al contexto |
| Falsos positivos semánticos | `verifyEmail` parece relevante para "verify user" | Contexto irrelevante, tokens desperdiciados |

**Resultado típico**: 70-85% del contexto enviado al LLM es ruido.

---

## KC-RAG: Recuperación por subgrafo de dependencias

```
Código fuente
    ↓ AST (tree-sitter + Python ast)
Cápsulas: función, clase, módulo — con metadatos (calls, imports, docstring)
    ↓ Índice Qdrant HNSW + match exacto por nombre/archivo
Candidatos relevantes (top 15 semánticos + exact match)
    ↓ Compresión adaptativa por tipo de tarea
Contexto estructural (~400–2000 tokens)
    ↓ Inyectado en el system prompt
El modelo responde directamente sin abrir archivos
```

### Tipos de tarea y compresión adaptativa

| Tipo | Qué incluye el contexto | Tokens aprox. |
|------|------------------------|---------------|
| `code_query` | Primera cápsula con cuerpo completo + firmas del resto | 500–2000 |
| `refactor` | Función target + todas sus callees + callers | 800–1500 |
| `search` | Mapa de funciones con indicador ✓doc/✗doc | 300–800 |
| `no_code` | Solo cápsulas de tipo documento | 100–500 |
| `code_gen` | Estructura de directorios sin cuerpos | 200–600 |

---

## Arquitectura

```
Cliente → POST /context a leo-code-mcp (:9898)
              ↓
         KC-RAG Sidecar (FastAPI Python)
              ↓ Indexer (AST) → Qdrant → Compressor
              ↓ contexto ~400-2000 tokens
         Respuesta comprimida al cliente
```

### Componentes

| Componente | Ubicación | Función |
|-----------|-----------|---------|
| **core** | `leo_code/core/` | Librería base: `Capsule`, parser AST, grafo BFS, `serialize_context`, cache Redis, benchmark |
| **rag** | `leo_code/rag/` | Pipeline KC-RAG: encoder, vector store Qdrant, compressor, classifier, agent loop, LLM providers |
| **server** | `leo_code/server/` | Servidor FastAPI: `/context`, `/search`, `/index`, `/preindex`, `/health`, `/stats` |

---

## Instalación

```bash
git clone https://github.com/manzzaano/leo-code.git
cd leo-code

# Instalar en modo editable (un solo paquete)
pip install -e .

# Variables de entorno (según proveedor)
export DEEPSEEK_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

---

## Uso del sidecar KC-RAG

```bash
# Arrancar el servidor en puerto 9898
leo-code-mcp --workers 2
# o directamente:
python -m leo_code.server.server
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/context` | KC-RAG pipeline completo: indexer → Qdrant → compress → contexto |
| `POST` | `/search` | Búsqueda semántica en el knowledge graph |
| `POST` | `/index` | Indexar un repositorio |
| `POST` | `/preindex` | Pre-indexar en background |
| `GET` | `/stats` | Estadísticas del índice |

### Ejemplo de uso

```bash
# Indexar un repo
curl -X POST http://localhost:9898/index \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/ruta/al/repo", "languages": "python,text"}'

# Consultar contexto
curl -X POST http://localhost:9898/context \
  -H "Content-Type: application/json" \
  -d '{"query": "qué hace la función retrieve_subgraph", "repo_path": "/ruta/al/repo"}'

# Búsqueda semántica
curl -X POST http://localhost:9898/search \
  -H "Content-Type: application/json" \
  -d '{"query": "vector store hnsw", "repo_path": "/ruta/al/repo", "top_k": 5}'
```

---

## Estructura interna

### Parser (`leo_code/core/parser.py`)

Extrae cápsulas del AST de Python sin LLM. Cada cápsula contiene:

```python
@dataclass
class Capsule:
    id: str           # hash SHA256 del path+línea+firma
    type: str         # function, class, module, variable, constant, document, file_header
    name: str         # nombre de la función/clase/módulo
    file_path: str    # ruta del archivo fuente
    start_line: int
    end_line: int
    language: str
    signature: str    # def foo(a: int, b: str) -> bool
    content: str      # cuerpo completo de la función/clase
    docstring: str    # docstring extraído
    calls: list[str]  # funciones que llama
    called_by: list[str]  # funciones que la llaman (resuelto por build_call_graph)
    imports: list[str]
    properties: dict  # parametros, tipo_retorno, lineas, module, metodos, etc.
```

Soporta Python vía `ast.parse()` y multi-lenguaje vía tree-sitter. Archivos `.txt` se parsean como cápsulas `document`.

### Compressor (`leo_code/rag/compressor.py`)

Compresión adaptativa según tipo de tarea:

- **code_query**: primera cápsula con cuerpo completo, resto con firma+docstring+relaciones. Incluye edges LLAMA.
- **code_edit**: función target + imports sin cuerpos completos.
- **code_gen**: estructura de directorios y archivos.
- **refactor**: función target + todas sus callees + todos sus callers con firmas.
- **search**: mini-mapa de funciones por archivo con indicador ✓doc/✗doc. Funciones sin docstring primero.
- **no_code**: cápsulas tipo documento con keyword match.

### Classifier (`leo_code/rag/classifier.py`)

Clasifica automáticamente la query en uno de 6 tipos usando señales léxicas en español e inglés:
`code_gen`, `code_edit`, `code_query`, `refactor`, `search`, `no_code`.

También detecta si la query necesita contexto de código (`snake_case`, `CamelCase`, palabras clave técnicas) y recomienda un presupuesto de tokens.

### Búsqueda híbrida (`leo_code/server/server.py`)

El endpoint `/context` combina:
1. **Exact match** por nombre de archivo, nombre de función, y palabras clave en la query
2. **Búsqueda semántica** Qdrant HNSW con embeddings `all-MiniLM-L6-v2` (384 dims)
3. Los resultados exactos se ordenan primero, fusionados con los semánticos

### LLM Providers (`leo_code/rag/llm/`)

Capa model-agnostic con auto-descubrimiento de providers vía variables de entorno:

| Provider | Variable de entorno |
|----------|-------------------|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| OpenAI / DeepSeek | `OPENAI_API_KEY` o `DEEPSEEK_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Google Gemini | `GOOGLE_API_KEY` o `GEMINI_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Cohere | `COHERE_API_KEY` |
| Ollama | Local (sin API key) |

### Cache (`leo_code/core/cache.py`)

Cache Redis con circuit breaker. Resultados de `/context` se cachean por 60s. Se invalida al indexar. Degrada gracefully si Redis no está disponible.

### Rate limiting

El sidecar aplica rate limiting: 30 requests por ventana de 10 segundos por IP.

---

## Seguridad

- **Sin API keys hardcodeadas**: todas las credenciales se leen de variables de entorno
- **Rate limiting**: protección básica contra abuso en el sidecar
- **Sin paths absolutos**: el código usa paths relativos o `os.path.abspath()` sobre inputs
- **Caché en `/cache`**: ignorado por `.gitignore`, no se commitea
- **Sin dependencia de LLM para indexar**: el parser AST es determinista, no filtra datos al exterior

---

## Requisitos

- Python >= 3.11
- Qdrant (local, sin servidor externo — usa `qdrant-client` en modo archivo)
- Redis (opcional, para cache L1/L2/L3)
- Dependencias opcionales por provider: `anthropic`, `openai`, `ollama`

---

## Licencia

MIT — [Ismael Manzano Leon](https://github.com/manzzaano) — 2026
