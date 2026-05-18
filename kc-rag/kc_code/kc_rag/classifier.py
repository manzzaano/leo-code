"""Classificador de tareas para KC-RAG adaptativo.

Determina:
1. Si la query necesita contexto de código del repo (needs_code_context)
2. El tipo de tarea (code_gen, code_edit, code_query, refactor, search, no_code)
3. El presupuesto de tokens recomendado para el contexto
"""

# Señales de que la query está relacionada con el código del repo
CODE_SIGNALS = [
    "función", "funcion", "function", "módulo", "modulo", "module",
    "clase", "class", "archivo", "file", "código", "codigo", "code",
    "import", "llama", "calls", "refactor", "implementa", "implementar",
    "dependencia", "dependency", "pipeline", "método", "metodo", "method",
    "parámetro", "parametro", "parameter", "docstring", "test",
    "parser", "indexer", "encoder", "compressor",
]

# Presupuesto de tokens por tipo de tarea
TOKEN_BUDGET = {
    "code_gen": 200,      # solo estructura de directorios
    "code_edit": 800,     # función target + dependencias directas
    "code_query": 1500,   # top 5 con docstrings, sin cuerpos completos
    "refactor": 2000,     # target + callers + callees
    "search": 500,        # mini-mapa ligero
    "no_code": 0,         # sin contexto de código
}

# Señales por tipo de tarea
TASK_SIGNALS = {
    "code_gen": [
        "crea", "nuevo", "añade", "añadir", "agrega", "genera", "escribe",
        "create", "new", "add", "generate", "write", "construye", "build",
    ],
    "code_edit": [
        "modifica", "cambia", "cambiar", "arregla", "fix", "corrige",
        "actualiza", "update", "edita", "edit", "cambiar",
    ],
    "code_query": [
        "explica", "que hace", "qué hace", "como funciona", "cómo funciona",
        "describe", "explain", "how does", "what does", "para que sirve",
    ],
    "refactor": [
        "refactor", "refactoriza", "reestructura", "extrae", "extraer",
        "separa", "unifica", "simplifica",
        # call-graph queries
        "que llama", "qué llama", "funciones llama", "métodos llama", "metodos llama",
        "quien llama", "quién llama", "dependencias de", "callers", "callees",
    ],
    "search": [
        "encuentra", "busca", "lista", "cuantas", "cuántas", "cuantos",
        "cuáles", "cuales", "find", "search", "list", "todas", "todos",
    ],
}


def needs_code_context(query: str) -> bool:
    """Determina si la query necesita contexto del código del repositorio."""
    q = query.lower()
    return any(s in q for s in CODE_SIGNALS)


def classify_task(query: str) -> str:
    """Clasifica el tipo de tarea según palabras clave en la query."""
    q = query.lower()

    scores = {}
    for task_type, signals in TASK_SIGNALS.items():
        scores[task_type] = sum(1 for s in signals if s in q)

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # Check if any code signal is present
        if needs_code_context(query):
            return "code_query"  # default para queries de código
        return "no_code"

    return best


def get_budget(query: str) -> int:
    """Retorna el presupuesto de tokens recomendado para esta query."""
    task_type = classify_task(query)
    return TOKEN_BUDGET.get(task_type, 1500)
