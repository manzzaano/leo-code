"""OllamaProvider: modelos locales vía Ollama API (chat completions)."""

import os
from typing import Optional

from leo_code.rag.llm.provider import LLMProvider, Response, TokenUsage, ToolCall


class OllamaProvider(LLMProvider):
    name = "ollama"
    context_window = 32768
    supports_tools = False

    def __init__(self, base_url: str | None = None,
                 model: str = "qwen2.5-coder:7b"):
        super().__init__(model=model)
        self.base_url = base_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import ollama
            self._client = ollama.Client(host=self.base_url)
        return self._client

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        try:
            ollama_msgs = []
            for m in messages:
                role = m["role"]
                content = m.get("content", "")
                if role == "tool":
                    role = "user"
                    content = f"[tool result] {content}"
                ollama_msgs.append({"role": role, "content": content})

            resp = self.client.chat(
                model=self.model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": 4096},
            )

            text = resp.get("message", {}).get("content", "")
            usage = TokenUsage(
                input_tokens=resp.get("prompt_eval_count", 0),
                output_tokens=resp.get("eval_count", 0),
            )
            return Response(text=text, usage=usage, finish_reason="stop",
                            tool_calls=[])
        except Exception as e:
            return Response(
                text=f"[OllamaProvider error: {e}. ¿Ollama corriendo en {self.base_url}?]",
                finish_reason="error",
            )

    async def stream(self, messages: list[dict], tools: Optional[list[dict]] = None):
        ollama_msgs = []
        for m in messages:
            role = m["role"]
            content = m.get("content", "")
            if role == "tool":
                role = "user"
                content = f"[tool result] {content}"
            ollama_msgs.append({"role": role, "content": content})

        try:
            stream = self.client.chat(
                model=self.model,
                messages=ollama_msgs,
                stream=True,
                options={"temperature": 0.2, "num_predict": 4096},
            )
            for chunk in stream:
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    yield delta
        except Exception:
            yield "[OllamaProvider error]"
