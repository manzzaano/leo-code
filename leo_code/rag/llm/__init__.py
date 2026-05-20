"""LLM: Capa de abstracción de modelos (model-agnostic).

Proveedores: Anthropic, OpenAI/DeepSeek, Google Gemini, Mistral, Groq, Cohere,
OpenRouter, Together AI, AWS Bedrock, Azure OpenAI, Ollama (local).

Catálogo: 40+ modelos con costes, límites y capacidades.
Auto-detección desde variables de entorno.
Routing por complejidad de tarea.
"""

from leo_code.rag.llm.provider import LLMProvider, Response, ToolCall, TokenUsage, CostTracker
from leo_code.rag.llm.anthropic import AnthropicProvider
from leo_code.rag.llm.openai_adapter import OpenAIProvider
from leo_code.rag.llm.ollama import OllamaProvider
from leo_code.rag.llm.openrouter import OpenRouterProvider
from leo_code.rag.llm.google import GoogleProvider
from leo_code.rag.llm.mistral import MistralProvider
from leo_code.rag.llm.groq import GroqProvider
from leo_code.rag.llm.cohere import CohereProvider
from leo_code.rag.llm.together import TogetherProvider
from leo_code.rag.llm.azure import AzureProvider
from leo_code.rag.llm.bedrock import BedrockProvider
from leo_code.rag.llm.catalog import CATALOG, ModelInfo, get_model_info, list_providers, list_models, estimate_cost
from leo_code.rag.llm.discovery import discover_providers, discover_models, recommended_model
from leo_code.rag.llm.routing import route, classify_complexity

__all__ = [
    "LLMProvider", "Response", "ToolCall", "TokenUsage", "CostTracker",
    # Providers
    "AnthropicProvider", "OpenAIProvider", "OllamaProvider", "OpenRouterProvider",
    "GoogleProvider", "MistralProvider", "GroqProvider", "CohereProvider",
    "TogetherProvider", "AzureProvider", "BedrockProvider",
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
    "deepseek": OpenAIProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
    "google": GoogleProvider,
    "gemini": GoogleProvider,
    "mistral": MistralProvider,
    "groq": GroqProvider,
    "cohere": CohereProvider,
    "together": TogetherProvider,
    "azure": AzureProvider,
    "bedrock": BedrockProvider,
}


def get_provider(name: str, **kwargs) -> LLMProvider:
    cls = _PROVIDER_REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(f"Proveedor no soportado: {name}. Disponibles: {list(_PROVIDER_REGISTRY)}")
    return cls(**kwargs)
