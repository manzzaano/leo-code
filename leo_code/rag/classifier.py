"""Classificador de tareas para KC-RAG adaptativo.

Determina:
1. Si la query necesita contexto de código del repo (needs_code_context)
2. El tipo de tarea (code_gen, code_edit, code_query, refactor, search, no_code)
3. El presupuesto de tokens recomendado para el contexto
"""

import re

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
    "code_gen": 800,
    "code_edit": 800,
    "code_query": 1500,
    "refactor": 2000,
    "search": 500,
    "no_code": 0,
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

_SNAKE_RE = re.compile(r"\w+_\w+")
_CAMEL_RE = re.compile(r"[a-záéíóúüñ]+[A-ZÁÉÍÓÚÜÑ]")
_TASK_SIGNAL_RES: dict[str, list[re.Pattern]] = {
    task_type: [re.compile(r"(?<!\w)" + re.escape(s) + r"(?!\w)") for s in signals]
    for task_type, signals in TASK_SIGNALS.items()
}


def needs_code_context(query: str) -> bool:
    """Determina si la query necesita contexto del código del repositorio."""
    q = query.lower()
    if any(s in q for s in CODE_SIGNALS):
        return True
    if _SNAKE_RE.search(query) or _CAMEL_RE.search(query):
        return True
    return False


def classify_task(query: str) -> str:
    """Clasifica el tipo de tarea según palabras clave en la query."""
    q = query.lower()

    scores = {}
    for task_type, patterns in _TASK_SIGNAL_RES.items():
        count = sum(1 for p in patterns if p.search(q))
        scores[task_type] = count

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        if needs_code_context(query):
            return "code_query"
        return "no_code"

    return best


def get_budget(query: str) -> int:
    """Retorna el presupuesto de tokens recomendado para esta query."""
    task_type = classify_task(query)
    return TOKEN_BUDGET.get(task_type, 1500)
