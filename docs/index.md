# leo-code — Docs

**Funciones completas con sus dependencias, no fragmentos de 500 tokens.**
**~90% de contexto relevante vs ~20% del chunking tradicional.**

👉 [**Empieza aquí: instala en 30 segundos →**](instalacion.md)

---

## ⚡ Instalación rápida

```bash
pip install leo-code
leo-code-mcp --workers 2
# ✓ KC-RAG corriendo en http://localhost:9898
```

---

## 📖 Guías

| Guía | Qué aprenderás |
|------|---------------|
| [Instalación rápida](instalacion.md) | pip install + arranque en 30 segundos |
| [Uso básico](uso.md) | Indexar un repo, consultar contexto, buscar |
| [Arquitectura](arquitectura.md) | Cómo funciona KC-RAG paso a paso |

## 🧠 Conceptos clave

| Concepto | Qué es |
|----------|--------|
| **Cápsula** | Unidad mínima de conocimiento: función, clase o módulo con metadatos del AST |
| **KC-RAG** | Pipeline que extrae cápsulas, las indexa en Qdrant y comprime el subgrafo relevante |
| **Compresión adaptativa** | El contexto se ajusta según el tipo de tarea: code_query, refactor, code_gen, etc. |

## 📚 Referencia

| Documento | Descripción |
|-----------|-------------|
| [API Endpoints](api.md) | `/context`, `/search`, `/index`, `/health`, `/stats` |
| [Configuración](configuracion.md) | Providers, cache Redis, rate limiting |
| [Parser AST](parser.md) | Python AST + tree-sitter multi-lenguaje |
| [Compresor](compresor.md) | Reglas de compresión por tipo de tarea |

---

## 🐍 SDK — Ejemplo rápido

```python
from leo_code.sdk import connect

client = connect("http://localhost:9898")
ctx = client.context("qué hace process_payment", "./mi-repo")
print(ctx.context)
# → Función process_payment() con sus dependencias: validate_card, apply_discount
```

---

**Repo**: [github.com/manzzaano/leo-code](https://github.com/manzzaano/leo-code)
