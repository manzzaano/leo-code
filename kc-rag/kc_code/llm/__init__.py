"""LLM: Capa de abstracción de modelos (model-agnostic).

Proveedores: Anthropic, OpenAI, Ollama, OpenRouter.
Catálogo: 22+ modelos con costes, límites y capacidades.
Auto-detección desde variables de entorno.
Routing por complejidad de tarea.
"""

from kc_code.llm.provider import LLMProvider, Response, ToolCall, TokenUsage, CostTracker
from kc_code.llm.anthropic import AnthropicProvider
from kc_code.llm.openai_adapter import OpenAIProvider
from kc_code.llm.ollama import OllamaProvider
from kc_code.llm.openrouter import OpenRouterProvider
from kc_code.llm.catalog import CATALOG, ModelInfo, get_model_info, list_providers, list_models, estimate_cost
from kc_code.llm.discovery import discover_providers, discover_models, recommended_model
from kc_code.llm.routing import route, classify_complexity

__all__ = [
    # Providers
    "LLMProvider", "Response", "ToolCall", "TokenUsage", "CostTracker",
    "AnthropicProvider", "OpenAIProvider", "OllamaProvider", "OpenRouterProvider",
    # Catalog
    "CATALOG", "ModelInfo", "get_model_info", "list_providers", "list_models", "estimate_cost",
    # Discovery
    "discover_providers", "discover_models", "recommended_model",
    # Routing
    "route", "classify_complexity",
    # Registry
    "get_provider",
]


_PROVIDER_REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "deepseek": OpenAIProvider,  # API compatible con OpenAI
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}


def get_provider(name: str, **kwargs) -> LLMProvider:
    """Obtiene un proveedor por nombre (anthropic, openai, ollama, openrouter)."""
    cls = _PROVIDER_REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(f"Proveedor no soportado: {name}. Disponibles: {list(_PROVIDER_REGISTRY)}")
    return cls(**kwargs)
