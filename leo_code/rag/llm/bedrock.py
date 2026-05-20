"""BedrockProvider: AWS Bedrock (Claude, Llama, Titan) vía boto3 converse API."""

import json
import os
from typing import Optional

from leo_code.rag.llm.provider import LLMProvider, Response, TokenUsage, ToolCall


class BedrockProvider(LLMProvider):
    name = "bedrock"
    context_window = 200000
    supports_tools = True

    def __init__(self, model: str = "anthropic.claude-sonnet-4-20250514-v1:0",
                 region: Optional[str] = None):
        super().__init__(model=model)
        self.model = model
        self.region = region or os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        system_parts = []
        msg_list = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                raw = m.get("content", "")
                if isinstance(raw, list):
                    blocks = []
                    for item in raw:
                        if item.get("type") == "text":
                            blocks.append({"text": item["text"]})
                        elif item.get("type") == "image_url":
                            url = item["image_url"]["url"]
                            if url.startswith("data:"):
                                header, b64 = url.split(",", 1)
                                mime = header.split(":")[1].split(";")[0]
                                blocks.append({"image": {"format": mime.split("/")[-1], "source": {"bytes": b64}}})
                    msg_list.append({"role": m["role"], "content": blocks if blocks else [{"text": ""}]})
                else:
                    msg_list.append({"role": m["role"], "content": [{"text": raw}]})

        kwargs = dict(
            modelId=self.model,
            messages=msg_list,
            inferenceConfig={"temperature": temperature, "maxTokens": 4096},
        )
        if system_parts:
            kwargs["system"] = [{"text": "\n\n".join(system_parts)}]
        if tools:
            kwargs["toolConfig"] = {
                "tools": [{"toolSpec": {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "inputSchema": {"json": t["function"].get("parameters", {})},
                }} for t in tools],
            }

        resp = self.client.converse(**kwargs)

        text = ""
        tool_calls = []
        output = resp.get("output", {}).get("message", {})
        for block in output.get("content", []):
            if "text" in block:
                text = block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(name=tu["name"], arguments=tu.get("input", {}), id=tu["toolUseId"]))

        usage_data = resp.get("usage", {})
        return Response(
            text=text,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage_data.get("inputTokens", 0),
                output_tokens=usage_data.get("outputTokens", 0),
            ),
            finish_reason="stop" if not tool_calls else "tool_use",
        )

    async def stream(self, messages: list[dict], tools: Optional[list[dict]] = None):
        result = await self.generate(messages, tools)
        yield result.text
