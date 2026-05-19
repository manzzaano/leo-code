"""AnthropicProvider: Claude Opus/Sonnet/Haiku vía Anthropic API."""

import json
import os
from typing import Optional

from leo_code.rag.llm.provider import LLMProvider, Response, ToolCall, TokenUsage


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    context_window = 200000
    supports_tools = True

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        # Extraer system messages; el resto va a messages
        system_parts = []
        non_system = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                non_system.append(m)
        system = "\n\n".join(system_parts)

        anthropic_msgs = self._convert_messages(non_system)
        anthropic_tools = self._convert_tools(tools) if tools else []

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 8096,
            "temperature": temperature,
            "messages": anthropic_msgs,
        }
        if system:
            kwargs["system"] = system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        resp = client.messages.create(**kwargs)

        text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(name=block.name, arguments=block.input, id=block.id)
                )

        usage = TokenUsage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
        finish: str = "tool_use" if tool_calls else "stop"
        return Response(text=text, tool_calls=tool_calls, usage=usage, finish_reason=finish)

    async def stream(self, messages: list[dict], tools: Optional[list[dict]] = None):
        # Streaming no necesario para el CLI — delegar a generate
        result = await self.generate(messages, tools)
        yield result.text

    # ------------------------------------------------------------------
    # Helpers de conversión de formato OpenAI → Anthropic
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        result = []
        i = 0
        while i < len(messages):
            m = messages[i]
            role = m["role"]

            if role == "tool":
                # Agrupar tool_result consecutivos en un único user message
                blocks = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tm = messages[i]
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tm.get("tool_call_id", ""),
                        "content": str(tm.get("content", "")),
                    })
                    i += 1
                result.append({"role": "user", "content": blocks})

            elif role == "assistant" and m.get("tool_calls"):
                # Convertir tool_calls del formato OpenAI a bloques Anthropic
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": args,
                    })
                result.append({"role": "assistant", "content": content})
                i += 1

            else:
                result.append({"role": role, "content": m.get("content", "")})
                i += 1

        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        result = []
        for t in tools:
            fn = t.get("function", t)
            result.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {
                    "type": "object", "properties": {},
                }),
            })
        return result
