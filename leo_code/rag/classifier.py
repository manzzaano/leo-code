"""Classificador de tareas para KC-RAG adaptativo.

Determina:
1. Si la query necesita contexto de código del repo (needs_code_context)
2. El tipo de tarea (code_gen, code_edit, code_query, refactor, search, debug, test_gen, no_code)
3. El presupuesto de tokens recomendado para el contexto
"""

import re

CODE_SIGNALS = [
    "función", "funcion", "function", "módulo", "modulo", "module",
    "clase", "class", "archivo", "file", "código", "codigo", "code",
    "import", "llama", "calls", "refactor", "implementa", "implementar",
    "dependencia", "dependency", "pipeline", "método", "metodo", "method",
    "parámetro", "parametro", "parameter", "docstring", "test",
    "parser", "indexer", "encoder", "compressor",
]

TOKEN_BUDGET = {
    "code_gen": 800,
    "code_edit": 800,
    "code_query": 1500,
    "refactor": 2000,
    "search": 500,
    "debug": 2500,
    "test_gen": 1500,
    "review": 1200,
    "optimize": 1500,
    "audit": 1000,
    "onboard": 600,
    "design_review": 1500,
    "no_code": 0,
}

TASK_SIGNALS = {
    "code_gen": [
        "crea", "nuevo", "añade", "añadir", "agrega", "genera", "escribe",
        "create", "new", "add", "generate", "write", "construye", "build",
    ],
    "code_edit": [
        "modifica", "cambia", "cambiar", "arregla", "fix", "corrige",
        "actualiza", "update", "edita", "edit",
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
    "debug": [
        "bug", "error", "falla", "fallo", "excepción", "excepcion", "exception",
        "traceback", "stack trace", "crash", "rompe", "roto", "no funciona",
        "debug", "debuggear", "depurar", "por qué falla", "por que falla",
        "por qué no", "por que no", "arregla", "fix", "corrige",
    ],
    "test_gen": [
        "test", "tests", "testear", "probar", "unit test", "unit tests",
        "prueba", "pruebas", "cobertura", "coverage", "pytest",
        "test de", "tests de", "genera test", "escribe test",
        "añade test", "agrega test", "create test", "write test",
        "escribe tests", "genera tests", "añade tests", "agrega tests",
        "crea test", "crea tests",
    ],
    "review": [
        "review", "revisa", "revisar", "revisión", "revision",
        "code review", "check", "inspecciona",
    ],
    "optimize": [
        "optimiza", "optimizar", "optimization", "performance",
        "lento", "lenta", "rápido", "rapido", "memoria", "memory",
        "perf", "profiling", "profile", "cuello", "bottleneck",
    ],
    "audit": [
        "seguridad", "security", "vulnerabilidad", "vulnerability",
        "audit", "auditoría", "auditoria", "safety", "safe",
        "inyección", "injection", "sql", "xss", "csrf",
        "secret", "token", "contraseña", "password", "expuesto",
        "busca vulnerabilidades", "vulnerable",
    ],
    "onboard": [
        "onboarding", "onboard", "introducción", "introduccion",
        "resumen", "summary", "overview", "arquitectura", "architecture",
        "estructura", "structure", "cómo empezar", "como empezar",
        "getting started", "guía", "guia", "guide",
    ],
    "design_review": [
        "diseño", "design", "ui", "ux", "landing", "página", "pagina",
        "copy", "color", "layout", "tipografía", "tipografia", "font",
        "imagen", "screenshot", "captura", "paleta", "palette",
        "accesibilidad", "accessibility", "wcag", "contraste", "contrast",
        "jerarquía", "hierarchy", "visual", "estilo", "style",
        "marca", "brand", "branding", "hero", "cta", "botón", "boton",
        "espaciado", "spacing", "responsive", "mobile", "desktop",
    ],
}

_SNAKE_RE = re.compile(r"\w+_\w+")
_CAMEL_RE = re.compile(r"[a-záéíóúüñ]+[A-ZÁÉÍÓÚÜÑ]")
_TASK_SIGNAL_RES: dict[str, list[re.Pattern]] = {
    task_type: [re.compile(r"(?<!\w)" + re.escape(s) + r"(?!\w)") for s in signals]
    for task_type, signals in TASK_SIGNALS.items()
}


def needs_code_context(query: str) -> bool:
    q = query.lower()
    if any(s in q for s in CODE_SIGNALS):
        return True
    if _SNAKE_RE.search(query) or _CAMEL_RE.search(query):
        return True
    return False


def classify_task(query: str) -> str:
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
    task_type = classify_task(query)
    return TOKEN_BUDGET.get(task_type, 1500)
