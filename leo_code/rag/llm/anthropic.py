"""AnthropicProvider: Claude (Opus/Sonnet/Haiku/Fable) vía la API oficial de Anthropic.

Modelo por defecto: claude-opus-4-8 (el más capaz de Anthropic; 1M de contexto).
Otros: anthropic/claude-sonnet-4-6, anthropic/claude-haiku-4-5, anthropic/claude-fable-5.

Dos formas de autenticarse (se detecta sola):
  • Suscripción (Claude Pro/Max), igual que Claude Code — SIN pagar por token.
    Inicia sesión una vez con `ant auth login` (abre el navegador con tu cuenta de
    Claude); leo usa ese token OAuth (Bearer + header oauth-2025-04-20). No pongas
    ANTHROPIC_API_KEY. También sirve ANTHROPIC_AUTH_TOKEN si ya tienes el token.
  • API key de pago: export ANTHROPIC_API_KEY=sk-ant-...
Si ANTHROPIC_API_KEY está puesta, manda; si no, se usa la suscripción/OAuth.
"""

import os
import json
from typing import Optional

# Header obligatorio para autenticar /v1/messages con un token OAuth de suscripción.
_OAUTH_BETA = "oauth-2025-04-20"

from leo_code.rag.llm.provider import LLMProvider, Response, ToolCall, TokenUsage

# Modelos que RECHAZAN temperature/top_p/top_k (devuelven 400): Opus 4.7/4.8, Fable 5,
# Mythos 5. Enviar sampling params a estos modelos rompe la petición.
_NO_SAMPLING = ("opus-4-7", "opus-4-8", "fable-5", "mythos-5")
# Modelos que soportan output_config.effort (low|medium|high|xhigh|max).
_SUPPORTS_EFFORT = ("opus-4-5", "opus-4-6", "opus-4-7", "opus-4-8", "sonnet-4-6", "fable-5", "mythos-5")


def _has(model: str, needles: tuple[str, ...]) -> bool:
    m = (model or "").lower()
    return any(n in m for n in needles)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    context_window = 1_000_000  # Opus 4.8 / Sonnet 4.6 / Fable 5
    supports_tools = True

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-4-8"):
        super().__init__(model=model)
        # api_key explícita o ANTHROPIC_API_KEY → modo pago. Si no hay, modo
        # suscripción/OAuth (token Bearer de `ant auth login` o ANTHROPIC_AUTH_TOKEN).
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.auth_token = "" if self.api_key else os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        self.model = model

    def _client(self):
        """Construye el cliente según la auth disponible. Con suscripción/OAuth añade
        el header beta obligatorio y evita mezclar api_key + auth_token (la API la rechaza)."""
        import anthropic
        if self.api_key:
            return anthropic.AsyncAnthropic(api_key=self.api_key), {}
        headers = {"anthropic-beta": _OAUTH_BETA}
        if self.auth_token:
            return anthropic.AsyncAnthropic(auth_token=self.auth_token, default_headers=headers), {}
        # Sin token explícito: deja que el SDK resuelva el perfil de `ant auth login`.
        return anthropic.AsyncAnthropic(default_headers=headers), {}

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
        effort: Optional[str] = None,
    ) -> Response:
        client, _ = self._client()

        # Anthropic separa el system del resto de mensajes.
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        non_system = [m for m in messages if m["role"] != "system"]
        system = "\n\n".join(p for p in system_parts if p)

        kwargs: dict = {
            "model": self.model,
            "max_tokens": self._effort_max_tokens(8096, effort),
            "messages": self._convert_messages(non_system),
        }
        # temperature: solo en modelos que la aceptan (Opus 4.7/4.8/Fable la rechazan con 400).
        if not _has(self.model, _NO_SAMPLING):
            kwargs["temperature"] = temperature
        # effort: control nativo de profundidad/coste en los modelos que lo soportan.
        if effort and _has(self.model, _SUPPORTS_EFFORT):
            kwargs["output_config"] = {"effort": effort}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        resp = await client.messages.create(**kwargs)

        # Refusal (clasificadores de seguridad, p.ej. Fable 5): HTTP 200 sin contenido útil.
        if getattr(resp, "stop_reason", None) == "refusal":
            return Response(text="[Anthropic rechazó la petición por política de seguridad.]",
                            usage=TokenUsage(input_tokens=resp.usage.input_tokens,
                                             output_tokens=resp.usage.output_tokens),
                            finish_reason="stop")

        text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(name=block.name, arguments=block.input, id=block.id))

        usage = TokenUsage(input_tokens=resp.usage.input_tokens,
                           output_tokens=resp.usage.output_tokens)
        finish: str = "tool_use" if tool_calls else "stop"
        return Response(text=text, tool_calls=tool_calls, usage=usage, finish_reason=finish)

    async def stream(self, messages: list[dict], tools: Optional[list[dict]] = None, effort: Optional[str] = None):
        # Streaming no necesario para el CLI — delegar a generate
        result = await self.generate(messages, tools, effort=effort)
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
                content = m.get("content", "")
                if isinstance(content, list):
                    blocks = _convert_content_array(content)
                    result.append({"role": role, "content": blocks})
                else:
                    result.append({"role": role, "content": content})
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


def _convert_content_array(content: list[dict]) -> list[dict]:
    """Convierte OpenAI content array → Anthropic content blocks."""
    blocks = []
    for item in content:
        if item.get("type") == "text":
            blocks.append({"type": "text", "text": item["text"]})
        elif item.get("type") == "image_url":
            url = item["image_url"]["url"]
            if url.startswith("data:"):
                header, b64 = url.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                })
    return blocks if blocks else [{"type": "text", "text": ""}]
