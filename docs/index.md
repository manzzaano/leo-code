# leo-code — Docs

Funciones completas con sus dependencias, no fragmentos de 500 tokens.
**~90% de contexto relevante contra el ~20% del chunking tradicional.**

## Empieza aquí

```bash
pip install leo-code
leo-code-mcp --workers 2
```

- [Instalación rápida](instalacion.md) — pip install + arranque en 30 segundos
- [Uso básico](uso.md) — indexar un repo, consultar contexto, buscar
- [Arquitectura](arquitectura.md) — cómo funciona KC-RAG paso a paso

## Conceptos clave

| Concepto | Qué es |
|----------|--------|
| **Cápsula** | Unidad mínima de conocimiento: función, clase o módulo con metadatos del AST |
| **KC-RAG** | Pipeline que extrae cápsulas, las indexa en Qdrant y comprime el subgrafo relevante |
| **Compresión adaptativa** | El contexto se ajusta según el tipo de tarea: code_query, refactor, code_gen, etc. |

## Referencia

- [API Endpoints](api.md) — `/context`, `/search`, `/index`, `/health`, `/stats`
- [Configuración](configuracion.md) — providers, cache Redis, rate limiting
- [Parser AST](parser.md) — Python AST + tree-sitter multi-lenguaje
- [Compresor](compresor.md) — reglas de compresión por tipo de tarea

---

```python
from leo_code.sdk import connect
client = connect("http://localhost:9898")
ctx = client.context("qué hace process_payment", "./mi-repo")
print(ctx.context)
```

**Repo**: [github.com/manzzaano/leo-code](https://github.com/manzzaano/leo-code) • **Licencia**: MIT
