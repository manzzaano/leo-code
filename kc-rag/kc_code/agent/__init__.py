"""Agent: loop de ejecución (consulta → KC-RAG → LLM → tools → repeat)."""

from kc_code.agent.loop import AgentLoop

__all__ = ["AgentLoop"]
