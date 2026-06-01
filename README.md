# 🧠 Tu LLM recibe el código que necesita, no el archivo entero

**El 80% de los tokens que pagas son basura. KC-RAG te da ~90% de señal.**

Cada vez que tu agente abre un archivo, paga tokens por líneas que no necesita.
KC-RAG extrae funciones completas con sus dependencias directas del AST, las indexa en Qdrant,
y devuelve solo el subgrafo relevante comprimido según tu tarea.

Sin fragmentos de 500 tokens. Sin dependencias perdidas. Sin ruido semántico.

<p align="center">
  <a href="#instalación"><strong>⚡ Deja de pagar por ruido — instala en 30s →</strong></a>
</p>

---

## ❌ El problema del chunking tradicional

| Lo que pasa | Por qué pasa | Lo que sufre tu LLM |
|-------------|-------------|---------------------|
| La función `verifyUser()` se parte por la mitad | El chunk de 500 tokens corta donde no debe | El LLM alucina porque ve código incompleto |
| Recuperas `verifyUser` pero no `hashPassword` | El chunking no sabe qué funciones llaman a otras | El bug real se queda fuera del contexto |
| `verifyEmail` aparece como resultado de "verify user" | La búsqueda semántica confunde nombres parecidos | Pagas tokens por código que no te sirve |

---

## ⚙️ Cómo funciona KC-RAG

```
Código fuente
    ↓ Analizamos el AST (tree-sitter + Python ast)
Cápsulas: funciones, clases y módulos completos con metadatos
    ↓ Indexamos en Qdrant (búsqueda semántica + exacta)
Candidatos relevantes (top 15 semánticos + match exacto por nombre)
    ↓ Comprimimos según tu tarea (code_query, refactor, code_gen…)
Contexto estructural (~400–2000 tokens)
    ↓ Se inyecta en el system prompt
El modelo responde sin haber abierto ningún archivo
```

## 📊 Resultados en repos reales

| Repo | Chunking tradicional | KC-RAG | Reducción |
|------|---------------------|--------|-----------|
| django (1.2M LOC) | ~8,200 tokens/consulta | ~1,100 tokens/consulta | **86% menos** |
| fastapi (65k LOC) | ~4,500 tokens/consulta | ~680 tokens/consulta | **85% menos** |
| leo-code (10k LOC) | ~2,300 tokens/consulta | ~420 tokens/consulta | **82% menos** |

> *Resultados estimados basados en consultas típicas de "explain function" y "find bug".*

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

| Componente | Ubicación | Responsabilidad |
|-----------|-----------|----------------|
| **core** | `leo_code/core/` | Define `Capsule`, parsea AST, construye grafo BFS, serializa contexto, cachea con Redis |
| **rag** | `leo_code/rag/` | Pipeline KC-RAG: encoder → Qdrant → compressor → classifier → agente loop → LLM |
| **server** | `leo_code/server/` | Expone FastAPI: `/context`, `/search`, `/index`, `/preindex`, `/health`, `/stats` |

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

## Reduce tu factura de tokens hoy

```bash
pip install leo-code && leo-code-mcp --workers 2
```

Primer contexto relevante en 2 comandos. Sin servidores externos. Sin configuración.

[← Volver al inicio](#tu-agente-ya-no-necesita-leer-archivos-enteros)

---

## Licencia

MIT — [Ismael Manzano Leon](https://github.com/manzzaano) — 2026
