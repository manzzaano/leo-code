"""AzureProvider: Azure OpenAI Service (GPT-4o via Azure)."""

import os
from typing import Optional

from leo_code.rag.llm.provider import LLMProvider, Response, TokenUsage, ToolCall


class AzureProvider(LLMProvider):
    name = "azure"
    context_window = 128000
    supports_tools = True

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None,
                 model: str = "gpt-4o"):
        super().__init__(model=model)
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
        return self._client

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        kwargs = dict(model=self.model, messages=messages, temperature=temperature, max_tokens=4096)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            import json
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))

        return Response(
            text=msg.content or "",
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
            ) if resp.usage else TokenUsage(),
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(self, messages: list[dict], tools: Optional[list[dict]] = None):
        kwargs = dict(model=self.model, messages=messages, temperature=0.2, max_tokens=4096, stream=True)
        if tools:
            kwargs["tools"] = tools
        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
