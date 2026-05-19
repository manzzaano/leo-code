"""OpenRouterProvider: passthrough a 100+ modelos vía OpenRouter API."""

from typing import Optional
from leo_code.rag.llm.provider import LLMProvider, Response


class OpenRouterProvider(LLMProvider):
    name = "openrouter"
    context_window = 128000
    supports_tools = True

    def __init__(self, api_key: Optional[str] = None, model: str = "anthropic/claude-sonnet-4"):
        super().__init__(model=model)
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        # TODO: Implementar vía OpenRouter API (base_url = https://openrouter.ai/api/v1)
        return Response(text="[OpenRouterProvider.generate() — pendiente de implementar]")

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ):
        yield "[OpenRouterProvider.stream() — pendiente de implementar]"
