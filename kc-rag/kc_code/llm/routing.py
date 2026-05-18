"""Routing de tareas entre modelos según complejidad + disponibilidad.

simple → local/barato → Ollama/DeepSeek/OpenRouter
medium → equilibrado → DeepSeek/Claude Sonnet/GPT-4o
complex → máxima calidad → Claude Opus/GPT-5.5/Gemini Pro
"""

from kc_code.llm.catalog import CATALOG, ModelInfo


COMPLEXITY_ROUTES: dict[str, list[str]] = {
    "simple": [
        "ollama/qwen2.5-coder:7b",
        "deepseek/deepseek-v4-flash",
        "openrouter/google/gemini-2.5-flash",
        "openrouter/meta-llama/llama-4-maverick",
    ],
    "medium": [
        "anthropic/claude-sonnet-4",
        "deepseek/deepseek-v4-pro",
        "openai/gpt-4o",
        "mistral/codestral",
    ],
    "complex": [
        "anthropic/claude-opus-4",
        "openai/gpt-5.5",
        "deepseek/deepseek-v4-pro",
        "google/gemini-2.5-pro",
    ],
    "code": [
        "anthropic/claude-sonnet-4",
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-v4-flash",
        "mistral/codestral",
        "ollama/qwen2.5-coder:14b",
    ],
}


def route(complexity: str = "medium", available_providers: list[str] | None = None) -> str:
    """Selecciona el mejor modelo disponible para la complejidad dada."""
    if available_providers is None:
        from kc_code.llm.discovery import discover_providers
        available_providers = discover_providers()

    candidates = COMPLEXITY_ROUTES.get(complexity, COMPLEXITY_ROUTES["medium"])

    for model_id in candidates:
        provider = model_id.split("/")[0]
        if provider in available_providers:
            return model_id

    # Fallback: cualquier modelo disponible
    if available_providers:
        from kc_code.llm.catalog import CATALOG
        p = available_providers[0]
        for m in CATALOG.values():
            if m.provider == p:
                return m.id

    return "deepseek/deepseek-chat"


def classify_complexity(query: str) -> str:
    """Clasifica la complejidad de una tarea por palabras clave."""
    q = query.lower()

    complex_markers = [
        "refactor", "arquitectura", "architecture", "rediseñar", "redesign",
        "multi-archivo", "multi-file", "cross-domain", "migrar", "migrate",
        "seguridad", "security", "optimizar sistema", "system-wide",
    ]
    simple_markers = [
        "qué hace", "que hace", "donde esta", "dónde está", "cuál es",
        "explica", "explain", "resume", "summarize", "lista", "list",
        "arreglar typo", "fix typo", "cambiar nombre", "rename",
    ]
    code_markers = [
        "función", "funcion", "function", "clase", "class", "módulo",
        "modulo", "module", "import", "escribe", "write", "genera",
        "generate", "código", "codigo", "code", "implementa", "implement",
    ]

    complex_score = sum(1 for m in complex_markers if m in q)
    simple_score = sum(1 for m in simple_markers if m in q)
    code_score = sum(1 for m in code_markers if m in q)

    if complex_score > 0:
        return "complex"
    if code_score > 0 and complex_score == 0:
        return "code"
    if simple_score > 0:
        return "simple"
    return "medium"
