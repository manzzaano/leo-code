# leo-code

**KC-RAG — Knowledge Capsule Retrieval-Augmented Generation para código.**

leo-code es un asistente de código que recupera contexto estructural por subgrafo de dependencias.
En lugar de chunking por longitud + embeddings, extrae cápsulas del AST y devuelve el subgrafo
relevante comprimido según el tipo de tarea.

## ¿Por qué leo-code?

| | Chunking tradicional | **leo-code (KC-RAG)** |
|---|---|---|
| Contexto | Fragmentos de 500 tokens | Funciones completas + dependencias |
| Calidad | 70-85% ruido | ~90% relevante |
| Tokens/query | ~20K promedio | ~1.5K comprimidos |
| Lenguajes | Cualquiera (texto plano) | Python (AST) + tree-sitter |
| Búsqueda | Solo embeddings | Híbrida: exacta + semántica |
| Providers | 1-2 | 12 providers, auto-detectados |

## Instalación rápida

```bash
pip install leo-code
leo-code-mcp --workers 2  # Arranca en :9898
```

## Uso desde Python

```python
from leo_code.sdk import connect
client = connect("http://localhost:9898")
ctx = client.context("qué hace la función process_payment", "./mi-repo")
print(ctx.context)
```
