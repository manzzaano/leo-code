"""AgentLoop: bucle iterativo de agente con KC-RAG integrado.

Flujo: consulta → indexer → Qdrant search → compress → LLM → tool calls → ejecutar → repeat.
"""

import os
import asyncio
from typing import Optional
from kc_code.agent.tools import ToolRegistry


class AgentLoop:
    """Bucle principal del agente: razona, ejecuta tools, itera hasta terminar."""

    def __init__(self, llm=None, tools: Optional[ToolRegistry] = None,
                 max_iterations: int = 10):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.max_iterations = max_iterations
        self._indexer = None
        self._vector_store = None
        self._indexed_repos = set()

    async def run(self, query: str, repo_path: str = ".",
                  model: str = "deepseek/deepseek-v4-flash",
                  use_kc_rag: bool = True) -> dict:
        """Ejecuta una consulta completa: retrieval → LLM → tools → respuesta."""
        if self.llm is None:
            self.llm = self._init_llm(model)

        repo_path = os.path.abspath(repo_path)

        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.append({"role": "user", "content": query})

        context = ""
        task_type = "code_query"
        if use_kc_rag:
            from kc_code.kc_rag.classifier import needs_code_context, classify_task, get_budget
            task_type = classify_task(query)
            if needs_code_context(query) or task_type in ("code_edit", "code_query", "refactor"):
                context = self._build_context(query, repo_path, task_type)

        tool_defs = self.tools.get_openai_definitions()
        total_tokens = 0

        if context:
            messages.insert(1, {"role": "system", "content": f"Contexto del codigo:\n{context}"})

        for iteration in range(self.max_iterations):
            resp = await self.llm.generate(messages, tool_defs, temperature=0.2)
            total_tokens += resp.usage.input_tokens + resp.usage.output_tokens

            if resp.tool_calls:
                for tc in resp.tool_calls:
                    result = self.tools.execute(tc.name, tc.arguments, repo_path)
                    assistant_msg = {
                        "role": "assistant",
                        "content": resp.text or "",
                    }
                    if resp.reasoning_content:
                        assistant_msg["reasoning_content"] = resp.reasoning_content
                    assistant_msg["tool_calls"] = [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": str(tc.arguments)},
                    }]
                    messages.append(assistant_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result[:4000],
                    })
                    try:
                        print(f"  [tool] {tc.name}({str(tc.arguments)[:80]}) -> {len(result)} chars")
                    except UnicodeEncodeError:
                        print(f"  [tool] {tc.name}(...) -> {len(result)} chars")
            else:
                return {
                    "respuesta": resp.text,
                    "iterations": iteration + 1,
                    "total_tokens": total_tokens,
                    "finish": "stop",
                }

        return {
            "respuesta": messages[-1].get("content", "Maximo de iteraciones alcanzado."),
            "iterations": self.max_iterations,
            "total_tokens": total_tokens,
            "finish": "max_iterations",
        }

    def _init_llm(self, model: str):
        from kc_code.llm import get_provider
        if "/" in model:
            provider_name, model_name = model.split("/", 1)
        else:
            provider_name, model_name = "openai", model

        if provider_name in ("deepseek", "openai"):
            return get_provider("openai",
                api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")),
                base_url="https://api.deepseek.com" if "deepseek" in model else "https://api.openai.com/v1",
                model=model_name)
        return get_provider(provider_name, model=model_name)

    def _build_context(self, query: str, repo_path: str, task_type: str = "code_query") -> str:
        """Construye contexto vía KC-RAG adaptativo: indexer → classify → Qdrant → compress."""
        try:
            if repo_path not in self._indexed_repos:
                self._ensure_indexed(repo_path)

            caps = self._indexer.get_capsules()
            if not caps:
                return ""

            from kc_code.kc_rag.classifier import get_budget
            budget = get_budget(query)

            top_ids = self._vector_store.search(query, top_k=10)
            top_caps = [caps[rid] for rid in top_ids if rid in caps]

            from kc_code.kc_rag.compressor import compress
            return compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type)
        except Exception as e:
            return f"[KC-RAG no disponible: {e}]"

    def _ensure_indexed(self, repo_path: str):
        from kc_code.indexer import Indexer
        from kc_code.kc_rag.vector_store import VectorStore

        self._indexer = Indexer()
        self._indexer.build(repo_path, verbose=False)

        self._vector_store = VectorStore(
            collection_name=f"kc_agent_{hash(repo_path) % 10000}",
            path="./cache/qdrant_agent"
        )
        self._vector_store.add(list(self._indexer.get_capsules().values()))
        self._indexed_repos.add(repo_path)

    def _system_prompt(self) -> str:
        return """Eres un asistente de programacion experto. Trabajas con un repositorio local.
Usa las herramientas disponibles (read_file, write_file, execute_command, git_diff, search_code) para:
1. Leer archivos relevantes antes de modificarlos.
2. Escribir cambios precisos con write_file (recibe file_path y content).
3. Ejecutar comandos para verificar con execute_command.
4. Mostrar diffs de tus cambios con git_diff.
5. Buscar patrones en el codigo con search_code.

Reglas:
- NO modifiques archivos sin leerlos primero con read_file.
- Haz cambios minimos y precisos.
- Usa execute_command para compilar/tests/linters.
- Si no sabes algo, dilo. No inventes.
- Para write_file: el parametro file_path es relativo al repo, content es el contenido completo del archivo.
- Para execute_command en Windows: usa comandos PowerShell o python."""
