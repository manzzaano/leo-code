"""OllamaProvider: modelos locales vía Ollama API."""

from typing import Optional
from leo_code.rag.llm.provider import LLMProvider, Response


class OllamaProvider(LLMProvider):
    name = "ollama"
    context_window = 8192
    supports_tools = False  # Ollama tool calling es limitado

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "qwen2.5-coder:7b"):
        super().__init__(model=model)
        self.base_url = base_url
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        # TODO: Implementar con ollama SDK
        return Response(text="[OllamaProvider.generate() — pendiente de implementar]")

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ):
        yield "[OllamaProvider.stream() — pendiente de implementar]"
