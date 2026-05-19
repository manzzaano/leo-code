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
    "code_gen": 800,      # actual code content (signatures, bodies)
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
        # análisis call-graph (lectura pura — no implican escritura)
        "que llama", "qué llama", "funciones llama", "métodos llama", "metodos llama",
        "quien llama", "quién llama", "dependencias de", "callers", "callees",
    ],
    "refactor": [
        "refactor", "refactoriza", "reestructura", "extrae", "extraer",
        "separa", "unifica", "simplifica",
    ],
    "search": [
        "encuentra", "busca", "lista", "cuantas", "cuántas", "cuantos",
        "cuáles", "cuales", "find", "search", "list", "todas", "todos",
    ],
}


def needs_code_context(query: str) -> bool:
    """Determina si la query necesita contexto del código del repositorio."""
    q = query.lower()
    if any(s in q for s in CODE_SIGNALS):
        return True
    # Heurística: snake_case o CamelCase → probablemente nombres de funciones/clases
    import re
    if re.search(r"\w+_\w+", query) or re.search(r"[a-záéíóúüñ]+[A-ZÁÉÍÓÚÜÑ]", query):
        return True
    return False


def classify_task(query: str) -> str:
    """Clasifica el tipo de tarea según palabras clave en la query."""
    import re
    q = query.lower()

    scores = {}
    for task_type, signals in TASK_SIGNALS.items():
        count = 0
        for s in signals:
            # Use word boundary matching to avoid false positives (e.g. "escribe" inside "describe")
            if re.search(r'(?<!\w)' + re.escape(s) + r'(?!\w)', q):
                count += 1
        scores[task_type] = count

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
