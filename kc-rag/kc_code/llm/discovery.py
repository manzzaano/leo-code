"""Auto-detección de providers desde variables de entorno.

Escanea env vars y detecta qué providers están disponibles.
También verifica Ollama local vía HTTP ping.
"""

import os
import httpx
from kc_code.llm.catalog import ModelInfo, CATALOG


_PROVIDER_ENV_VARS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY", "DEEPSEEK_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
}


def discover_providers() -> list[str]:
    """Retorna lista de providers detectados en el entorno."""
    available = []

    for provider, env_vars in _PROVIDER_ENV_VARS.items():
        for var in env_vars:
            if os.getenv(var):
                available.append(provider)
                break

    if _check_ollama():
        available.append("ollama")

    return available


def _check_ollama(base_url: str = "http://localhost:11434") -> bool:
    """Verifica si Ollama está corriendo localmente."""
    try:
        with httpx.Client(timeout=1.0) as client:
            resp = client.get(f"{base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def discover_models(provider_filter: str | None = None) -> list[ModelInfo]:
    """Retorna modelos disponibles según providers detectados."""
    providers = discover_providers()
    if provider_filter:
        providers = [p for p in providers if p == provider_filter]

    models = []
    for p in providers:
        for model in CATALOG.values():
            if model.provider == p:
                models.append(model)
    return models


def recommended_model(task: str = "general") -> str:
    """Recomienda el mejor modelo según providers disponibles y tipo de tarea."""
    providers = discover_providers()

    task_prefs = {
        "code": ["anthropic/claude-sonnet-4", "deepseek/deepseek-v4-pro",
                  "deepseek/deepseek-v4-flash", "ollama/qwen2.5-coder:14b"],
        "general": ["anthropic/claude-sonnet-4", "openai/gpt-4o",
                     "deepseek/deepseek-v4-flash"],
        "cheap": ["deepseek/deepseek-v4-flash", "ollama/qwen2.5-coder:7b",
                   "openrouter/google/gemini-2.5-flash"],
        "local": ["ollama/qwen2.5-coder:14b", "ollama/deepseek-coder-v2",
                   "ollama/llama3.1:8b"],
    }

    candidates = task_prefs.get(task, task_prefs["general"])
    for model_id in candidates:
        provider = model_id.split("/")[0]
        if provider in providers:
            return model_id

    if providers:
        p = providers[0]
        for m in CATALOG.values():
            if m.provider == p:
                return m.id

    return "deepseek/deepseek-chat"  # fallback
