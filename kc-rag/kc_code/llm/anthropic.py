"""AnthropicProvider: Claude Opus/Sonnet/Haiku vía Anthropic API."""

from typing import Optional
from kc_code.llm.provider import LLMProvider, Response


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    context_window = 200000
    supports_tools = True

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        # TODO: Implementar con anthropic SDK
        return Response(text="[AnthropicProvider.generate() — pendiente de implementar]")

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ):
        # TODO: Implementar streaming con anthropic SDK
        yield "[AnthropicProvider.stream() — pendiente de implementar]"
