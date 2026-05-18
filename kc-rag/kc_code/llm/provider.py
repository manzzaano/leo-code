"""LLMProvider ABC + tipos de datos compartidos."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

from kc_code.llm.catalog import ModelInfo, CATALOG


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = ""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class Response:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: Literal["stop", "tool_use", "length", "error"] = "stop"
    reasoning_content: str = ""


class CostTracker:
    """Acumula coste estimado de uso de LLM."""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0
        self.total_cache_read = 0
        self.total_cache_write = 0

    def add(self, usage: TokenUsage):
        self.total_input += usage.input_tokens
        self.total_output += usage.output_tokens
        self.total_cache_read += usage.cache_read_tokens
        self.total_cache_write += usage.cache_write_tokens

    def estimate_cost(self, model_id: str) -> float:
        from kc_code.llm.catalog import estimate_cost
        return estimate_cost(model_id, self.total_input, self.total_output,
                              self.total_cache_read, self.total_cache_write)

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.total_output


class LLMProvider(ABC):
    """Interfaz común para todos los proveedores de LLM."""

    name: str = "base"
    context_window: int = 128000
    supports_tools: bool = True

    def __init__(self, model: str = ""):
        self.model = model
        self.cost_tracker = CostTracker()
        self._model_info: Optional[ModelInfo] = None

    @property
    def model_info(self) -> Optional[ModelInfo]:
        if self._model_info is None and self.model:
            for key, info in CATALOG.items():
                if info.provider == self.name and info.id.endswith(self.model):
                    self._model_info = info
                    break
            if self._model_info is None:
                self._model_info = CATALOG.get(self.model) or CATALOG.get(f"{self.name}/{self.model}")
        return self._model_info

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> Response:
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ):
        ...

    def track(self, usage: TokenUsage):
        self.cost_tracker.add(usage)

    def cost_estimate(self) -> float:
        model_id = f"{self.name}/{self.model}" if self.name != "base" else self.model
        return self.cost_tracker.estimate_cost(model_id)
