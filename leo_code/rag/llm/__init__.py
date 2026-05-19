"""LLM: Capa de abstracción de modelos (model-agnostic).

Proveedores: Anthropic, OpenAI, Ollama, OpenRouter.
Catálogo: 22+ modelos con costes, límites y capacidades.
Auto-detección desde variables de entorno.
Routing por complejidad de tarea.
"""

from leo_code.rag.llm.provider import LLMProvider, Response, ToolCall, TokenUsage, CostTracker
from leo_code.rag.llm.anthropic import AnthropicProvider
from leo_code.rag.llm.openai_adapter import OpenAIProvider
from leo_code.rag.llm.ollama import OllamaProvider
from leo_code.rag.llm.openrouter import OpenRouterProvider
from leo_code.rag.llm.catalog import CATALOG, ModelInfo, get_model_info, list_providers, list_models, estimate_cost
from leo_code.rag.llm.discovery import discover_providers, discover_models, recommended_model
from leo_code.rag.llm.routing import route, classify_complexity

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
