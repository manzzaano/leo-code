"""Catálogo estático de modelos LLM con costes, límites y capacidades.

Metadata estructurada para cada modelo, costes y capacidades.
Costes en $/1M tokens (precios orientativos mayo 2026).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelInfo:
    id: str                     # "anthropic/claude-sonnet-4"
    provider: str               # "anthropic"
    name: str                   # "Claude Sonnet 4"
    cost_input: float = 0       # $/1M tokens
    cost_output: float = 0
    cost_cache_read: float = 0
    cost_cache_write: float = 0
    context_window: int = 128000
    max_output: int = 4096
    supports_tools: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False
    tier: str = "medium"        # "free", "budget", "medium", "premium"


CATALOG: dict[str, ModelInfo] = {
    # Anthropic
    "anthropic/claude-opus-4": ModelInfo(
        id="anthropic/claude-opus-4", provider="anthropic", name="Claude Opus 4",
        cost_input=15, cost_output=75, cost_cache_read=1.5, cost_cache_write=7.5,
        context_window=200000, max_output=32000, supports_vision=True, supports_reasoning=True,
        tier="premium",
    ),
    "anthropic/claude-sonnet-4": ModelInfo(
        id="anthropic/claude-sonnet-4", provider="anthropic", name="Claude Sonnet 4",
        cost_input=3, cost_output=15, cost_cache_read=0.3, cost_cache_write=7.5,
        context_window=200000, max_output=32000, supports_vision=True,
        tier="medium",
    ),
    "anthropic/claude-haiku-4": ModelInfo(
        id="anthropic/claude-haiku-4", provider="anthropic", name="Claude Haiku 4",
        cost_input=0.8, cost_output=4, cost_cache_read=0.08, cost_cache_write=2,
        context_window=200000, max_output=8192,
        tier="budget",
    ),

    # OpenAI
    "openai/gpt-5.5": ModelInfo(
        id="openai/gpt-5.5", provider="openai", name="GPT-5.5",
        cost_input=5, cost_output=40, cost_cache_read=2.5, cost_cache_write=10,
        context_window=256000, max_output=16384, supports_vision=True,
        tier="premium",
    ),
    "openai/gpt-5-mini": ModelInfo(
        id="openai/gpt-5-mini", provider="openai", name="GPT-5 Mini",
        cost_input=1, cost_output=8, cost_cache_read=0.5, cost_cache_write=2,
        context_window=256000, max_output=16384, supports_vision=True,
        tier="budget",
    ),
    "openai/gpt-4o": ModelInfo(
        id="openai/gpt-4o", provider="openai", name="GPT-4o",
        cost_input=2.5, cost_output=10, cost_cache_read=1.25, cost_cache_write=5,
        context_window=128000, max_output=16384, supports_vision=True,
        tier="medium",
    ),

    # DeepSeek
    "deepseek/deepseek-v4-pro": ModelInfo(
        id="deepseek/deepseek-v4-pro", provider="openai", name="DeepSeek V4 Pro",
        cost_input=1.74, cost_output=3.48, cost_cache_read=0.14, cost_cache_write=0.14,
        context_window=1048576, max_output=384000, supports_reasoning=True,
        tier="premium",
    ),
    "deepseek/deepseek-v4-flash": ModelInfo(
        id="deepseek/deepseek-v4-flash", provider="openai", name="DeepSeek V4 Flash",
        cost_input=0.14, cost_output=0.28, cost_cache_read=0.014, cost_cache_write=0.014,
        context_window=1048576, max_output=384000,
        tier="budget",
    ),
    "deepseek/deepseek-chat": ModelInfo(
        id="deepseek/deepseek-chat", provider="openai", name="DeepSeek V3",
        cost_input=0.29, cost_output=0.43, context_window=65536, max_output=8192,
        tier="budget",
    ),
    "deepseek/deepseek-reasoner": ModelInfo(
        id="deepseek/deepseek-reasoner", provider="openai", name="DeepSeek R1",
        cost_input=0.55, cost_output=2.19, context_window=65536, max_output=8192,
        supports_reasoning=True, tier="medium",
    ),

    # OpenRouter (precios promedio)
    "openrouter/anthropic/claude-sonnet-4": ModelInfo(
        id="openrouter/anthropic/claude-sonnet-4", provider="openrouter", name="Claude Sonnet 4 (OR)",
        cost_input=3, cost_output=15, context_window=200000, max_output=32000,
        supports_vision=True, tier="medium",
    ),
    "openrouter/openai/gpt-4o": ModelInfo(
        id="openrouter/openai/gpt-4o", provider="openrouter", name="GPT-4o (OR)",
        cost_input=2.5, cost_output=10, context_window=128000, max_output=16384,
        supports_vision=True, tier="medium",
    ),
    "openrouter/google/gemini-2.5-flash": ModelInfo(
        id="openrouter/google/gemini-2.5-flash", provider="openrouter", name="Gemini 2.5 Flash (OR)",
        cost_input=0.15, cost_output=0.60, context_window=1048576, max_output=8192,
        tier="free",
    ),
    "openrouter/meta-llama/llama-4-maverick": ModelInfo(
        id="openrouter/meta-llama/llama-4-maverick", provider="openrouter", name="Llama 4 Maverick (OR)",
        cost_input=0.20, cost_output=0.80, context_window=256000, max_output=8192,
        tier="free",
    ),

    # Google
    "google/gemini-2.5-pro": ModelInfo(
        id="google/gemini-2.5-pro", provider="google", name="Gemini 2.5 Pro",
        cost_input=1.25, cost_output=10, context_window=1048576, max_output=65536,
        supports_vision=True, supports_reasoning=True, tier="premium",
    ),
    "google/gemini-2.5-flash": ModelInfo(
        id="google/gemini-2.5-flash", provider="google", name="Gemini 2.5 Flash",
        cost_input=0.15, cost_output=0.60, context_window=1048576, max_output=8192,
        supports_vision=True, tier="free",
    ),

    # Mistral
    "mistral/mistral-large": ModelInfo(
        id="mistral/mistral-large", provider="mistral", name="Mistral Large",
        cost_input=2, cost_output=6, context_window=128000, max_output=131072,
        tier="medium",
    ),
    "mistral/mistral-small": ModelInfo(
        id="mistral/mistral-small", provider="mistral", name="Mistral Small",
        cost_input=0.2, cost_output=0.6, context_window=32000, max_output=4096,
        tier="budget",
    ),
    "mistral/codestral": ModelInfo(
        id="mistral/codestral", provider="mistral", name="Codestral",
        cost_input=1, cost_output=3, context_window=256000, max_output=32000,
        tier="medium",
    ),

    # Ollama (local — $0 API cost, coste eléctrico insignificante)
    "ollama/qwen2.5-coder:7b": ModelInfo(
        id="ollama/qwen2.5-coder:7b", provider="ollama", name="Qwen 2.5 Coder 7B",
        cost_input=0, cost_output=0, context_window=32768, max_output=4096,
        tier="free",
    ),
    "ollama/qwen2.5-coder:14b": ModelInfo(
        id="ollama/qwen2.5-coder:14b", provider="ollama", name="Qwen 2.5 Coder 14B",
        cost_input=0, cost_output=0, context_window=32768, max_output=4096,
        tier="free",
    ),
    "ollama/qwen2.5-coder:32b": ModelInfo(
        id="ollama/qwen2.5-coder:32b", provider="ollama", name="Qwen 2.5 Coder 32B",
        cost_input=0, cost_output=0, context_window=32768, max_output=4096,
        tier="free",
    ),
    "ollama/deepseek-coder-v2": ModelInfo(
        id="ollama/deepseek-coder-v2", provider="ollama", name="DeepSeek Coder V2",
        cost_input=0, cost_output=0, context_window=32768, max_output=4096,
        tier="free",
    ),
    "ollama/llama3.1:8b": ModelInfo(
        id="ollama/llama3.1:8b", provider="ollama", name="Llama 3.1 8B",
        cost_input=0, cost_output=0, context_window=131072, max_output=4096,
        tier="free",
    ),

    # Groq (LPU — ultra-fast inference)
    "groq/llama-4-scout-17b-16e-instruct": ModelInfo(
        id="groq/llama-4-scout-17b-16e-instruct", provider="groq", name="Llama 4 Scout 17B",
        cost_input=0.10, cost_output=0.40, context_window=131072, max_output=8192,
        tier="free",
    ),
    "groq/llama-4-maverick-17b-128e-instruct": ModelInfo(
        id="groq/llama-4-maverick-17b-128e-instruct", provider="groq", name="Llama 4 Maverick 17B",
        cost_input=0.20, cost_output=0.60, context_window=131072, max_output=8192,
        tier="budget",
    ),
    "groq/deepseek-r1-distill-llama-70b": ModelInfo(
        id="groq/deepseek-r1-distill-llama-70b", provider="groq", name="DeepSeek R1 Distill 70B",
        cost_input=0.75, cost_output=0.99, context_window=131072, max_output=8192,
        tier="medium",
    ),

    # Cohere
    "cohere/command-r-plus": ModelInfo(
        id="cohere/command-r-plus", provider="cohere", name="Command R+",
        cost_input=2.5, cost_output=10, context_window=128000, max_output=4096,
        tier="medium",
    ),
    "cohere/command-r": ModelInfo(
        id="cohere/command-r", provider="cohere", name="Command R",
        cost_input=0.5, cost_output=1.5, context_window=128000, max_output=4096,
        tier="budget",
    ),

    # Together AI
    "together/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": ModelInfo(
        id="together/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8", provider="together",
        name="Llama 4 Maverick 17B",
        cost_input=0.20, cost_output=0.60, context_window=131072, max_output=4096,
        tier="budget",
    ),
    "together/Qwen/Qwen3-Coder-480B-A35B-Instruct": ModelInfo(
        id="together/Qwen/Qwen3-Coder-480B-A35B-Instruct", provider="together",
        name="Qwen 3 Coder 480B",
        cost_input=1.20, cost_output=2.50, context_window=32768, max_output=8192,
        tier="medium",
    ),
    "together/deepseek-ai/DeepSeek-V3": ModelInfo(
        id="together/deepseek-ai/DeepSeek-V3", provider="together", name="DeepSeek V3",
        cost_input=1.25, cost_output=1.25, context_window=65536, max_output=8192,
        tier="medium",
    ),

    # Bedrock
    "bedrock/anthropic.claude-sonnet-4-20250514-v1:0": ModelInfo(
        id="bedrock/anthropic.claude-sonnet-4-20250514-v1:0", provider="bedrock",
        name="Claude Sonnet 4 (Bedrock)",
        cost_input=3, cost_output=15, context_window=200000, max_output=32000,
        supports_vision=True, tier="medium",
    ),
    "bedrock/anthropic.claude-opus-4-20250514-v1:0": ModelInfo(
        id="bedrock/anthropic.claude-opus-4-20250514-v1:0", provider="bedrock",
        name="Claude Opus 4 (Bedrock)",
        cost_input=15, cost_output=75, context_window=200000, max_output=32000,
        supports_vision=True, supports_reasoning=True, tier="premium",
    ),
    "bedrock/meta.llama4-maverick-17b-instruct-v1:0": ModelInfo(
        id="bedrock/meta.llama4-maverick-17b-instruct-v1:0", provider="bedrock",
        name="Llama 4 Maverick (Bedrock)",
        cost_input=0.30, cost_output=0.60, context_window=131072, max_output=4096,
        tier="budget",
    ),

    # Azure OpenAI
    "azure/gpt-4o": ModelInfo(
        id="azure/gpt-4o", provider="azure", name="GPT-4o (Azure)",
        cost_input=2.5, cost_output=10, context_window=128000, max_output=16384,
        supports_vision=True, tier="medium",
    ),
    "azure/gpt-4o-mini": ModelInfo(
        id="azure/gpt-4o-mini", provider="azure", name="GPT-4o Mini (Azure)",
        cost_input=0.15, cost_output=0.60, context_window=128000, max_output=16384,
        supports_vision=True, tier="budget",
    ),
}


def get_model_info(provider: str, model: str) -> Optional[ModelInfo]:
    """Busca info de modelo por provider + nombre."""
    key = f"{provider}/{model}"
    return CATALOG.get(key) or CATALOG.get(model)


def list_providers() -> list[str]:
    """Lista providers únicos en el catálogo."""
    return sorted(set(m.provider for m in CATALOG.values()))


def list_models(provider: str | None = None) -> list[ModelInfo]:
    """Lista modelos, opcionalmente filtrados por provider."""
    if provider:
        return [m for m in CATALOG.values() if m.provider == provider]
    return list(CATALOG.values())


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int,
                  cache_read: int = 0, cache_write: int = 0) -> float:
    """Estima coste en USD para un uso dado."""
    info = CATALOG.get(model_id)
    if not info:
        return 0
    return (
        info.cost_input * input_tokens / 1_000_000
        + info.cost_output * output_tokens / 1_000_000
        + info.cost_cache_read * cache_read / 1_000_000
        + info.cost_cache_write * cache_write / 1_000_000
    )
