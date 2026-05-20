"""AgentLoop: bucle iterativo de agente con KC-RAG integrado.

Flujo: consulta → indexer → Qdrant search → compress → LLM → tool calls → ejecutar → repeat.
"""

import os
import time
import asyncio
from typing import Optional
from leo_code.rag.agent.tools import ToolRegistry


class AgentLoop:
    """Bucle principal del agente: razona, ejecuta tools, itera hasta terminar."""

    def __init__(self, llm=None, tools: Optional[ToolRegistry] = None,
                 max_iterations: int = 10, permission_manager=None):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.max_iterations = max_iterations
        self.perms = permission_manager
        self._indexer = None
        self._vector_store = None
        self._indexed_repos = set()
        self._recent_calls: set[str] = set()  # anti-loop
        self._tool_call_count = 0

    async def run(self, query: str, repo_path: str = ".",
                   model: str = "deepseek/deepseek-v4-flash",
                   use_kc_rag: bool = True,
                   history: list[dict] | None = None,
                   session_id: str | None = None) -> dict:
        """Ejecuta una consulta completa vía stream_run (wrapper)."""
        result = {
            "respuesta": "", "steps": [], "iterations": 0,
            "total_tokens": 0, "duration_ms": 0, "finish": "stop",
            "model": model, "session_id": session_id,
        }
        self._recent_calls.clear()
        async for event in self.stream_run(
            query, repo_path=repo_path, model=model,
            use_kc_rag=use_kc_rag, history=history, session_id=session_id,
        ):
            if event["type"] == "done":
                for key in ("respuesta", "total_tokens", "iterations", "duration_ms", "finish"):
                    if key in event:
                        result[key] = event[key]
        return result

    def _persist_turn(self, session_id: str, query: str, answer: str, model: str, tokens: int):
        try:
            from leo_code.session import SessionManager
            sm = SessionManager()
            sm.add_message(session_id, "user", query, tokens=0)
            sm.add_message(session_id, "assistant", answer, tokens=tokens)
        except Exception:
            pass

    def create_session(self, repo_path: str, model: str = "") -> str:
        from leo_code.session import SessionManager
        sm = SessionManager()
        s = sm.create_session(repo_path, model)
        return s.id

    def list_sessions(self, limit: int = 20):
        from leo_code.session import SessionManager
        sm = SessionManager()
        return sm.list_sessions(limit)

    async def goal_stream_run(self, goal_text: str, repo_path: str = ".",
                              model: str = "deepseek/deepseek-v4-flash",
                              plugin_manager=None, skill_manager=None):
        """Goal mode: plan → execute → verify → re-plan. No para hasta completar."""
        from leo_code.rag.agent.goal import GoalRunner
        self.interrupt = False
        if self.llm is None:
            self.llm = self._init_llm(model)
        repo_path = os.path.abspath(repo_path)
        runner = GoalRunner(self, self.tools, self.llm)
        async for event in runner.run(goal_text, repo_path, model,
                                       plugin_manager, skill_manager):
            if self.interrupt:
                runner.cancel()
            yield event

    async def stream_run(self, query: str, repo_path: str = ".",
                         model: str = "deepseek/deepseek-v4-flash",
                         use_kc_rag: bool = True,
                         history: list[dict] | None = None,
                         session_id: str | None = None,
                         images: list[str] | None = None,
                         plugin_manager=None,
                         skill_manager=None):
        """Streaming: KC-RAG context → LLM tokens → tool calls → repeat.

        Yields dicts: {"type": "context"|"token"|"tool_start"|"tool_result"|"tool_end"|"done"}
        images: lista de paths a imágenes para análisis de visión.
        plugin_manager: PluginManager instancia para plugins.
        skill_manager: SkillManager instancia para auto-skills.
        """
        t0 = time.time()
        self.interrupt = False

        if self.llm is None:
            self.llm = self._init_llm(model)
        repo_path = os.path.abspath(repo_path)

        # Session history
        session = None
        if session_id:
            from leo_code.session import SessionManager
            sm = SessionManager()
            session = sm.get_session(session_id)
            if session:
                repo_path = session.repo_path

        messages = [{"role": "system", "content": self._system_prompt()}]
        if session:
            messages.extend(sm.get_history(session_id, limit=40))
        elif history:
            messages.extend(history)

        # Build user message con texto + imágenes como content array
        user_content = _build_user_content(query, images or [], repo_path)
        messages.append({"role": "user", "content": user_content})

        # KC-RAG context
        context = ""
        task_type = "code_query"
        if use_kc_rag:
            from leo_code.rag.classifier import needs_code_context, classify_task
            task_type = classify_task(query)
            if needs_code_context(query) or task_type in ("code_edit", "code_query", "refactor", "debug"):
                context = self._build_context(query, repo_path, task_type)
                if context:
                    yield {"type": "context", "task_type": task_type, "tokens": len(context) // 2}

        if context:
            messages.insert(1, {"role": "system", "content": f"Contexto del codigo:\n{context}"})

        # Plugin context injection
        if plugin_manager:
            plugins_ctx = plugin_manager.pre_context(query, [])
            if plugins_ctx:
                messages.insert(1, {"role": "system", "content": f"Contexto de plugins:\n{plugins_ctx}"})
            plugin_info = plugin_manager.info()
            if plugin_info:
                yield {"type": "plugins", "plugins": [{"name": p.name, "type": p.type, "running": p.running, "tool_count": getattr(p, 'tool_count', 0)} for p in plugin_info]}

        # Auto-skills activation
        active_skills = []
        if skill_manager:
            skill_manager.load_skills(repo_path)
            active_skills = skill_manager.match(query, task_type=task_type, file_context=[])
            if active_skills:
                skill_manager.inject(active_skills, messages)
                yield {"type": "skills", "skills": [{"name": s.name, "source": s.source, "priority": s.priority} for s in active_skills]}

        tool_defs = self.tools.get_openai_definitions()
        total_tokens = 0
        self._tool_call_count = 0

        for iteration in range(self.max_iterations):
            if self.interrupt:
                yield {"type": "done", "respuesta": "[Interrumpido]", "iterations": iteration,
                       "total_tokens": total_tokens, "duration_ms": int((time.time() - t0) * 1000)}
                return

            # Compactar historial si crece demasiado
            messages = _compact_messages(messages, keep_last=6)

            # Stream tokens
            text = ""
            tool_calls: list[dict] = []
            async for chunk in self.llm.stream(messages, tool_defs):
                if self.interrupt:
                    break
                if isinstance(chunk, str):
                    text += chunk
                    yield {"type": "token", "text": chunk}
                elif isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_calls.append(chunk)

            if self.interrupt:
                yield {"type": "done", "respuesta": text or "[Interrumpido]", "iterations": iteration + 1,
                       "total_tokens": total_tokens, "duration_ms": int((time.time() - t0) * 1000)}
                return

            if not tool_calls:
                total_tokens += len(text) // 4
                if session_id:
                    self._persist_turn(session_id, query, text, model, total_tokens)
                yield {"type": "done", "respuesta": text, "iterations": iteration + 1,
                       "total_tokens": total_tokens, "duration_ms": int((time.time() - t0) * 1000)}
                return

            # Execute tools
            for tc in tool_calls:
                args = tc.get("args", {})
                # Permission check
                if self.perms:
                    allowed, reason = self.perms.check(tc["name"], args)
                    if not allowed:
                        yield {"type": "tool_start", "name": tc["name"], "args": args}
                        yield {"type": "tool_result", "name": tc["name"], "output": f"[Bloqueado: {reason}]"}
                        continue

                # Loop detection
                call_key = f"{tc['name']}:{str(args)[:80]}"
                if call_key in self._recent_calls:
                    yield {"type": "tool_start", "name": tc["name"], "args": args}
                    yield {"type": "tool_result", "name": tc["name"], "output": f"[Llamada repetida a {tc['name']} — busca otra estrategia]"}
                    continue
                self._recent_calls.add(call_key)
                self._tool_call_count += 1

                yield {"type": "tool_start", "name": tc["name"], "args": args}
                result = self.tools.execute(tc["name"], args, repo_path)
                # Trim resultes largos
                if len(result) > 1500:
                    result = result[:1500] + f"\n[{len(result)} chars total. Usa search_code para explorar.]"
                yield {"type": "tool_result", "name": tc["name"], "output": result}
                messages.append({"role": "assistant", "content": text or "",
                                 "tool_calls": [{"id": tc.get("id", ""), "type": "function",
                                                  "function": {"name": tc["name"], "arguments": str(args)}}]})
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result[:2000]})
                total_tokens += len(result) // 4

            text = ""

        yield {"type": "done", "respuesta": "Máximo de iteraciones alcanzado.", "iterations": self.max_iterations,
               "total_tokens": total_tokens, "duration_ms": int((time.time() - t0) * 1000)}

    def _init_llm(self, model: str):
        from leo_code.rag.llm import get_provider
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

            from leo_code.rag.classifier import get_budget
            budget = get_budget(query)

            top_ids = self._vector_store.search(query, top_k=10)
            top_caps = [caps[rid] for rid in top_ids if rid in caps]

            from leo_code.rag.compressor import compress
            return compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type)
        except Exception as e:
            return f"[KC-RAG no disponible: {e}]"

    def _ensure_indexed(self, repo_path: str):
        from leo_code.rag.indexer import Indexer
        from leo_code.rag.vector_store import VectorStore

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
Usa las herramientas disponibles para completar la tarea:

Herramientas:
- read_file: leer archivos (antes de modificarlos siempre)
- write_file: escribir/sobrescribir archivos completos
- replace_in_file: cambios quirurgicos (especifica old_string exacto)
- list_files: explorar la estructura del repositorio
- execute_command: ejecutar comandos (pytest, lint, git, etc.)
- run_tests: ejecutar tests (acepta path y keyword opcionales)
- git_diff: ver los cambios que has hecho
- search_code: buscar patrones en el codigo (usa rg)

Reglas:
- NO modifiques archivos sin leerlos primero con read_file.
- Prefiere replace_in_file sobre write_file para cambios pequenos.
- Usa run_tests para verificar que los cambios no rompen nada.
- Haz cambios minimos y precisos.
- Si no sabes algo, dilo. No inventes.
- Para execute_command en Windows: usa comandos PowerShell o python.
- Si recibes imagenes, analizalas visualmente: colores, layout, tipografia, jerarquia."""


def _build_user_content(query: str, images: list[str], repo_path: str) -> list[dict]:
    """Construye content array con texto + imágenes para modelos de visión."""
    content = [{"type": "text", "text": query}]
    for img_path in images:
        try:
            from leo_code.core.parser import extract_image_capsule
            capsules = extract_image_capsule(img_path)
            if capsules:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": capsules[0].content},
                })
        except Exception:
            content.append({"type": "text", "text": f"[No se pudo cargar imagen: {img_path}]"})
    return content


def _compact_messages(messages: list[dict], keep_last: int = 6) -> list[dict]:
    """Compacta historial preservando system + user original + ultimos mensajes."""
    if len(messages) <= keep_last + 2:
        return messages
    head = messages[:2]
    recent = messages[-keep_last:]
    old_count = len(messages) - keep_last - 2
    if old_count > 0:
        summary = {"role": "system", "content": f"[Historial compactado: {old_count} mensajes omitidos para ahorrar tokens]"}
        return head + [summary] + recent
    return messages
