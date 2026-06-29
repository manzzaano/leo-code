"""AgentLoop: bucle iterativo de agente con KC-RAG integrado.

Flujo: consulta → indexer → Qdrant search → compress → LLM → tool calls → ejecutar → repeat.
"""

import os
import json
import time
import logging
import asyncio
from pathlib import Path
from typing import Optional
from leo_code.rag.agent.tools import ToolRegistry
from leo_code.core.metrics import get_metrics
from leo_code.rag.conversation_history import ConversationHistory

log = logging.getLogger("leo.agent")

_ERROR_MARKERS = ("error", "traceback", "exception", "[bloqueado", "no encontrad",
                  "falló", "fallo:", "not found", "denied")


def _looks_like_error(result: str) -> bool:
    """Heurística: ¿el resultado de un tool parece un error? (para effort routing)."""
    low = (result or "").lower()
    return any(m in low for m in _ERROR_MARKERS)


# YAGNI behavioral skill (Ponytail): solo en tareas de escribir/editar código.
_YAGNI_DIRECTIVE = (
    "Para esta tarea de escribir/editar codigo aplica minimalismo (YAGNI): "
    "primero reutiliza lo que ya existe en el repo; usa stdlib o una dependencia ya "
    "instalada antes de anadir una nueva; el codigo mas simple que funciona gana. "
    "No anadas abstracciones, configuracion ni andamiaje no pedidos. Cambios minimos."
)
_YAGNI_TASKS = ("code_gen", "code_edit", "refactor")

_VERBOSITY_BLOCK = """

Estilo de respuesta (ahorra tokens de salida):
- Ve al grano. Nada de preambulo ('Claro', 'Por supuesto', 'Voy a...') ni de recapitular lo que ya se dijo.
- No repitas el codigo del contexto si no aporta; referencia simbolo y archivo:linea.
- Responde lo justo: conclusiones primero, sin relleno. Fragmentos OK si quedan claros."""

# Tasks de AMPLITUD (review/arquitectura/onboarding): necesitan respuesta extensa.
# El benchmark N=3 mostró que verbosity steering + effort cap les HACEN DAÑO
# (-1.2 a -2.2). Para estas: verbosity OFF + effort completo. El classifier es
# poco fiable aquí (arquitectura cae en code_query), así que combinamos task_type
# fiable + señales léxicas de amplitud.
_BREADTH_TASKS = ("review", "design_review", "onboard", "audit")
_BREADTH_SIGNALS = (
    "arquitectura", "architecture", "traza", "trace", "cadena completa",
    "flujo completo", "todo el sistema", "como se relacionan", "overview",
    "vista general", "todos los tipos", "explica el sistema", "end-to-end",
    "audita", "auditoria", "code review",
)


def _is_breadth(query: str, task_type: str) -> bool:
    if task_type in _BREADTH_TASKS:
        return True
    q = (query or "").lower()
    return any(s in q for s in _BREADTH_SIGNALS)


class AgentLoop:
    """Bucle principal del agente: razona, ejecuta tools, itera hasta terminar."""

    def __init__(self, llm=None, tools: Optional[ToolRegistry] = None,
                 max_iterations: int = 10, permission_manager=None):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.max_iterations = max_iterations
        self.perms = permission_manager
        self._indexer = None
        self._conversation_history = None
        self._indexed_repos = set()
        self._recent_calls: dict[str, int] = {}  # anti-loop: cuenta repeticiones IDÉNTICAS
        self._tool_call_count = 0

    async def run(self, query: str, repo_path: str = ".",
                   model: str = "deepseek/deepseek-v4-flash",
                   use_kc_rag: bool = True,
                   history: list[dict] | None = None,
                   session_id: str | None = None) -> dict:
        """Ejecuta con generate() para tool calling fiable (no streaming)."""
        t0 = time.time()
        self._recent_calls.clear()
        self._tool_call_count = 0
        self.interrupt = False

        t_index_ms = 0
        t_classify_ms = 0
        t_search_ms = 0
        t_compress_ms = 0
        t_llm_ms = 0

        if self.llm is None:
            self.llm = self._init_llm(model)
        repo_path = os.path.abspath(repo_path)

        messages = [{"role": "system", "content": self._system_prompt()}]

        # Memoria persistente cross-sesión (Mem0): recupera facts relevantes del repo.
        _mem = None
        try:
            from leo_code.session import SessionManager
            _mem = SessionManager()
            _recalled = _mem.recall(repo_path, query, limit=3)
            if _recalled:
                messages.append({"role": "system",
                    "content": "Memoria del repo (sesiones previas):\n- " + "\n- ".join(_recalled)})
        except Exception:
            _mem = None

        # Instincts (aprendizaje continuo): inyecta patrones aprendidos relevantes.
        _instincts = None
        try:
            from leo_code.learning import InstinctStore
            _instincts = InstinctStore(base_dir="./cache/learning", project_id=repo_path)
            _block = _instincts.inject_block(query)
            if _block:
                messages.append({"role": "system", "content": _block})
        except Exception:
            _instincts = None

        if session_id:
            from leo_code.session import SessionManager
            sm = SessionManager()
            session = sm.get_session(session_id)
            if session:
                repo_path = session.repo_path
                messages.extend(sm.get_history(session_id, limit=30))
        elif history:
            messages.extend(history)

        # KC-RAG context
        context = ""
        breadth = False
        if use_kc_rag:
            from leo_code.rag.classifier import classify_task
            t_c0 = time.perf_counter()
            task_type = classify_task(query)
            t_classify_ms = (time.perf_counter() - t_c0) * 1000
            breadth = _is_breadth(query, task_type)
            # Verbosity steering: solo en tasks NO-amplitud (las de amplitud pierden calidad).
            if not breadth and os.getenv("LEO_VERBOSITY", "1") != "0":
                messages.append({"role": "system", "content": _VERBOSITY_BLOCK.strip()})
            if task_type in _YAGNI_TASKS:
                messages.append({"role": "system", "content": _YAGNI_DIRECTIVE})
            ctx, timings = self._build_context(query, repo_path, task_type)
            if ctx:
                context = ctx
                t_index_ms = timings.get("t_index_ms", 0)
                t_search_ms = timings.get("t_search_ms", 0)
                t_compress_ms = timings.get("t_compress_ms", 0)
                messages.insert(1, {"role": "system", "content": f"Contexto del codigo:\n{context}"})

        messages.append({"role": "user", "content": query})

        tool_defs = self.tools.get_definitions()
        total_tokens = 0
        all_text = ""
        llm_iterations = 0
        edited = False
        noop_nudges = 0
        edit_task = use_kc_rag and task_type in ("code_edit", "code_gen", "refactor", "debug")

        # Effort routing (Headroom): turno trivial (continúa tras tool sin error)
        # baja el esfuerzo; query inicial / tras error → esfuerzo completo.
        next_effort: Optional[str] = None

        for iteration in range(self.max_iterations):
            if self.interrupt:
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                return {"respuesta": "[Interrumpido]", "total_tokens": total_tokens,
                        "iterations": iteration, "duration_ms": duration_ms}

            # Compactar historial (keep_last=16 para preservar pares assistant+tool)
            messages = _compact_messages(messages, keep_last=16)

            t_llm0 = time.perf_counter()
            resp = await self.llm.generate(messages, tool_defs, temperature=0.2, effort=next_effort)
            t_llm_ms += (time.perf_counter() - t_llm0) * 1000
            llm_iterations += 1
            total_tokens += resp.usage.input_tokens + resp.usage.output_tokens
            text = resp.text or ""
            all_text += text

            if not resp.tool_calls:
                # No-op guard: tarea de edición que "termina" sin haber editado nada
                # (p.ej. "ahora aplicaré los cambios" y para). Empuja a actuar de verdad.
                if edit_task and not edited and noop_nudges < 2:
                    noop_nudges += 1
                    messages.append({"role": "assistant", "content": text or "(continuando)"})
                    messages.append({"role": "user", "content":
                        "Aun NO has aplicado ningun cambio al archivo. No anuncies lo que haras: "
                        "EJECUTALO ahora mismo con replace_in_file o write_file, y verifica con run_tests."})
                    continue
                if session_id:
                    self._persist_turn(session_id, query, text, model, total_tokens)
                # Save to conversation history
                if self._conversation_history and context:
                    self._conversation_history.save_conversation(query, context, total_tokens, iteration + 1)
                # Memoria persistente: guarda un fact del intercambio (Mem0).
                if _mem is not None and text:
                    try:
                        _mem.remember(repo_path, f"P: {query[:120]} -> R: {text[:200]}")
                    except Exception:
                        pass
                # Aprendizaje: mina las observaciones de tools de esta sesión.
                if _instincts is not None and self._tool_call_count >= 3:
                    try:
                        _instincts.mine_observations(trigger=query, min_count=3)
                    except Exception:
                        pass
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                log.info(f"query completed | task_type={task_type if use_kc_rag else 'none'} | "
                        f"index={t_index_ms:.0f}ms classify={t_classify_ms:.0f}ms search={t_search_ms:.0f}ms "
                        f"compress={t_compress_ms:.0f}ms llm={t_llm_ms:.0f}ms × {llm_iterations} iter | "
                        f"tokens={total_tokens} total_ms={duration_ms}")
                return {"respuesta": text, "total_tokens": total_tokens,
                        "iterations": iteration + 1,
                        "duration_ms": duration_ms}

            # Build ONE assistant message with ALL tool_calls
            all_tool_calls = []
            for tc in resp.tool_calls:
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                tc_id = tc.id or f"call_{iteration}_{hash(tc.name) % 10000}"
                all_tool_calls.append({
                    "id": tc_id, "type": "function",
                    "function": {"name": tc.name,
                                 "arguments": json.dumps(args, ensure_ascii=False)}
                })

            messages.append({
                "role": "assistant",
                "content": text or "(using tools)",
                "tool_calls": all_tool_calls,
            })

            # Execute each tool and append result
            any_error = False
            ran_tool = False
            for tc, tc_data in zip(resp.tool_calls, all_tool_calls):
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                call_key = _loop_key(tc.name, args)
                self._recent_calls[call_key] = self._recent_calls.get(call_key, 0) + 1
                if self._recent_calls[call_key] >= _LOOP_BLOCK_THRESHOLD:
                    messages.append({"role": "tool", "tool_call_id": tc_data["id"],
                                     "content": f"[Llamada idéntica repetida {self._recent_calls[call_key]}× — cambia de estrategia o de argumentos]"})
                    continue
                self._tool_call_count += 1

                result = self.tools.execute(tc.name, args, repo_path)
                ran_tool = True
                if _looks_like_error(result):
                    any_error = True
                if _instincts is not None:
                    try:
                        _instincts.observe({"tool": tc.name, "args": args, "ok": not _looks_like_error(result)})
                    except Exception:
                        pass
                if tc.name in ("write_file", "replace_in_file"):
                    edited = True
                if len(result) > 4000:
                    ref = self.tools.store_full(result)
                    result = result[:4000] + f"\n[truncado {len(result)} chars — usa retrieve_full('{ref}') UNA vez para el resto; NO inventes otras refs]"
                messages.append({"role": "tool", "tool_call_id": tc_data["id"], "content": result[:1000]})
                total_tokens += len(result) // 4

            # Routing: continuación tras tools OK → bajo esfuerzo; tras error → completo.
            next_effort = "low" if (ran_tool and not any_error and not breadth and os.getenv("LEO_EFFORT", "1") != "0") else None

            # SÍNTESIS: tras suficientes iteraciones, fuerza una respuesta final
            # consolidada sin tools (evita devolver texto parcial tipo "(using tools)").
            if iteration >= 8:
                final = await self._finalize(messages, query)
                answer = final or all_text or "[Sin respuesta]"
                if session_id:
                    self._persist_turn(session_id, query, answer, model, total_tokens)
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                log.info(f"query finalized at iter {iteration} | tokens={total_tokens} ms={duration_ms}")
                return {"respuesta": answer, "total_tokens": total_tokens,
                        "iterations": iteration + 1,
                        "duration_ms": duration_ms}

        final = await self._finalize(messages, query)
        duration_ms = int((time.time() - t0) * 1000)
        get_metrics().record_query(total_tokens, duration_ms,
                                  t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
        log.warning(f"query max_iterations reached | iterations={self.max_iterations} tokens={total_tokens} ms={duration_ms}")
        return {"respuesta": final or all_text or f"[No completado en {self.max_iterations} iteraciones.]",
                "total_tokens": total_tokens, "iterations": self.max_iterations,
                "duration_ms": duration_ms}

    async def _finalize(self, messages: list[dict], query: str = "") -> str:
        """Una llamada final SIN tools para consolidar la respuesta, anclada a la pregunta original."""
        try:
            instr = (
                "YA NO HAY MAS HERRAMIENTAS DISPONIBLES. No intentes llamar a ninguna ni "
                "escribas codigo de exploracion. Con TODO lo que ya investigaste, responde "
                "AHORA de forma completa y autocontenida a la pregunta original del usuario:\n"
                f"\"{query}\""
            )
            msgs = messages + [{"role": "user", "content": instr}]
            resp = await self.llm.generate(msgs, [], temperature=0.3)
            return resp.text or ""
        except Exception as e:
            log.debug(f"finalize fallo: {e}")
            return ""

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

        t_index_ms = 0
        t_classify_ms = 0
        t_search_ms = 0
        t_compress_ms = 0
        t_llm_ms = 0

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
        breadth = False
        if use_kc_rag:
            from leo_code.rag.classifier import needs_code_context, classify_task
            t_c0 = time.perf_counter()
            task_type = classify_task(query)
            t_classify_ms = (time.perf_counter() - t_c0) * 1000
            breadth = _is_breadth(query, task_type)
            if not breadth and os.getenv("LEO_VERBOSITY", "1") != "0":
                messages.append({"role": "system", "content": _VERBOSITY_BLOCK.strip()})
            if task_type in _YAGNI_TASKS:
                messages.append({"role": "system", "content": _YAGNI_DIRECTIVE})
            if needs_code_context(query) or task_type in ("code_edit", "code_query", "refactor", "debug"):
                context, timings = self._build_context(query, repo_path, task_type)
                t_index_ms = timings.get("t_index_ms", 0)
                t_search_ms = timings.get("t_search_ms", 0)
                t_compress_ms = timings.get("t_compress_ms", 0)
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
        self._recent_calls.clear()   # anti-loop por query (no arrastrar entre turnos de chat)
        all_text = ""
        llm_iterations = 0
        next_effort: Optional[str] = None  # effort routing (Headroom)

        for iteration in range(self.max_iterations):
            if self.interrupt:
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                yield {"type": "done", "respuesta": "[Interrumpido]", "iterations": iteration,
                       "total_tokens": total_tokens, "duration_ms": duration_ms}
                return

            # Compactar historial si crece demasiado
            messages = _compact_messages(messages, keep_last=6)

            # Stream tokens
            text = ""
            tool_calls: list[dict] = []
            reasoning = ""   # reasoning_content del turno (thinking models: hay que devolverlo)
            t_llm0 = time.perf_counter()
            # Últimas 2 iteraciones: sin tools → el modelo DEBE sintetizar respuesta con lo
            # que ya recopiló (evita agotar iteraciones explorando sin responder nunca).
            active_tools = None if iteration >= self.max_iterations - 2 else tool_defs
            async for chunk in self.llm.stream(messages, active_tools, effort=next_effort):
                if self.interrupt:
                    break
                if isinstance(chunk, str):
                    text += chunk
                    all_text += chunk
                    yield {"type": "token", "text": chunk}
                elif isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_calls.append(chunk)
                elif isinstance(chunk, dict) and chunk.get("type") == "reasoning":
                    reasoning = chunk.get("content", "")
            t_llm_ms += (time.perf_counter() - t_llm0) * 1000
            llm_iterations += 1

            if self.interrupt:
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                yield {"type": "done", "respuesta": text or "[Interrumpido]", "iterations": iteration + 1,
                       "total_tokens": total_tokens, "duration_ms": duration_ms}
                return

            if not tool_calls:
                total_tokens += len(text) // 4
                if session_id:
                    self._persist_turn(session_id, query, text, model, total_tokens)
                # Save to conversation history
                if self._conversation_history and context:
                    self._conversation_history.save_conversation(query, context, total_tokens, iteration + 1)
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                log.info(f"stream_run completed | task_type={task_type} | "
                        f"index={t_index_ms:.0f}ms classify={t_classify_ms:.0f}ms search={t_search_ms:.0f}ms "
                        f"compress={t_compress_ms:.0f}ms llm={t_llm_ms:.0f}ms × {llm_iterations} iter | "
                        f"tokens={total_tokens} total_ms={duration_ms}")
                yield {"type": "done", "respuesta": text, "iterations": iteration + 1,
                       "total_tokens": total_tokens, "duration_ms": duration_ms}
                return

            # Execute tools.
            # UN solo mensaje `assistant` con TODOS los tool_calls (spec OpenAI: tool_calls
            # paralelos + un mensaje `tool` por cada uno), args en JSON (no repr Python), y
            # reasoning_content reinyectado si el modelo lo exige (DeepSeek V4 thinking).
            any_error = False
            ran_tool = False
            for i, tc in enumerate(tool_calls):
                tc["_id"] = tc.get("id") or f"call_{iteration}_{i}"
            messages.append(_assistant_tool_msg(text, tool_calls, reasoning))

            for tc in tool_calls:
                args = tc.get("args", {})
                tc_id = tc["_id"]

                # Permission check
                if self.perms:
                    allowed, reason = self.perms.check(tc["name"], args)
                    if not allowed:
                        any_error = True
                        yield {"type": "tool_start", "name": tc["name"], "args": args}
                        yield {"type": "tool_result", "name": tc["name"], "output": f"[Bloqueado: {reason}]"}
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"[Bloqueado: {reason}]"})
                        continue

                # Loop detection: solo la MISMA tool con args IDÉNTICOS repetida ≥3×.
                call_key = _loop_key(tc["name"], args)
                self._recent_calls[call_key] = self._recent_calls.get(call_key, 0) + 1
                if self._recent_calls[call_key] >= _LOOP_BLOCK_THRESHOLD:
                    msg = f"[Llamada idéntica a {tc['name']} repetida {self._recent_calls[call_key]}× — cambia de estrategia o de argumentos]"
                    yield {"type": "tool_start", "name": tc["name"], "args": args}
                    yield {"type": "tool_result", "name": tc["name"], "output": msg}
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": msg})
                    continue
                self._tool_call_count += 1

                yield {"type": "tool_start", "name": tc["name"], "args": args}
                result = self.tools.execute(tc["name"], args, repo_path)
                ran_tool = True
                if _looks_like_error(result):
                    any_error = True
                # Trim resultes largos
                if len(result) > 4000:
                    ref = self.tools.store_full(result)
                    result = result[:4000] + f"\n[truncado {len(result)} chars — usa retrieve_full('{ref}') UNA vez para el resto; NO inventes otras refs]"
                yield {"type": "tool_result", "name": tc["name"], "output": result}
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result[:1000]})
                total_tokens += len(result) // 4

            # Routing: continuación tras tools OK → bajo esfuerzo; tras error → completo.
            next_effort = "low" if (ran_tool and not any_error and not breadth and os.getenv("LEO_EFFORT", "1") != "0") else None

            # After tools, prompt to finish
            if tool_calls and iteration >= 8:
                messages.append({"role": "system", "content": "URGENTE: Da tu respuesta final AHORA. No pidas mas herramientas."})

            text = ""

        # Fallback: si no terminó con respuesta, usa texto acumulado
        fallback_resp = all_text if all_text else f"[No se pudo completar en {self.max_iterations} iteraciones. {self._tool_call_count} tool calls ejecutadas.]"
        duration_ms = int((time.time() - t0) * 1000)
        get_metrics().record_query(total_tokens, duration_ms,
                                  t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
        log.warning(f"stream_run max_iterations | iterations={self.max_iterations} tokens={total_tokens} ms={duration_ms}")
        yield {"type": "done", "respuesta": fallback_resp, "iterations": self.max_iterations,
               "total_tokens": total_tokens, "duration_ms": duration_ms}

    def _init_llm(self, model: str):
        from leo_code.rag.llm import get_provider
        if "/" in model:
            provider_name, model_name = model.split("/", 1)
        else:
            provider_name, model_name = "openai", model

        if provider_name in ("deepseek", "openai"):
            base_url = "https://api.deepseek.com" if provider_name == "deepseek" or "deepseek" in model else "https://api.openai.com/v1"
            return get_provider("openai",
                api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")),
                base_url=base_url,
                model=model_name)
        return get_provider(provider_name, model=model_name)

    def _build_context(self, query: str, repo_path: str, task_type: str = "code_query") -> tuple[str, dict]:
        """El agente usa su PROPIO motor: inyecta el contexto KC-RAG comprimido
        (compute_context, ~80% menos tokens que leer archivos) y cablea el cerebro
        determinista (GraphQuery) a las tools, para que el agente llame
        trace/impact/who_calls (con prueba, cero alucinación) en vez de grepear.

        Devuelve (contexto_comprimido, timings) — contrato con run()/goal.py.
        """
        from leo_code import engine
        timings = {"t_index_ms": 0, "t_search_ms": 0, "t_compress_ms": 0}
        try:
            repo = os.path.abspath(repo_path)
            t_idx0 = time.perf_counter()
            with engine._index_lock:
                need = repo not in engine._indexed_repos
            if need:
                engine._do_index(repo)
            timings["t_index_ms"] = (time.perf_counter() - t_idx0) * 1000
            # Cablea capsules + GraphQuery (cerebro) a las tools cada llamada (barato).
            self.tools.set_index(engine._get_indexer().get_capsules())
            # Inyecta el subgrafo comprimido en vez de que el agente lea archivos enteros.
            t_c0 = time.perf_counter()
            ctx = engine.compute_context(repo, query, task_type).get("context", "")
            timings["t_compress_ms"] = (time.perf_counter() - t_c0) * 1000
            return ctx, timings
        except Exception as e:
            log.exception(f"Index/context error: {e}")
            return "", timings

    def _ensure_indexed(self, repo_path: str):
        from leo_code.rag.indexer import Indexer
        from pathlib import Path

        cache_dir = Path(repo_path) / ".leo-code"
        cache_path = cache_dir / "kc_index.json.gz"

        self._indexer = Indexer()

        # Carga persistente + sync incremental: si el cache existe, cargarlo y
        # re-parsear SOLO lo cambiado (en vez de rebuild completo). Solo build
        # full cuando no hay cache.
        if cache_path.exists():
            cache_mtime = cache_path.stat().st_mtime
            self._indexer.load(str(cache_path))
            if self._is_cache_stale(cache_path, repo_path):
                log.debug(f"Cache stale → sync incremental: {repo_path}")
                self._indexer.sync(repo_path, since_mtime=cache_mtime)
                self._indexer.save(str(cache_path))
        else:
            log.debug(f"Building index for {repo_path}")
            self._indexer.build(repo_path, verbose=False)
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._indexer.save(str(cache_path))

        # Initialize conversation history
        self._conversation_history = ConversationHistory(repo_path)

        self._indexed_repos.add(repo_path)

    def _is_cache_stale(self, cache_path: Path, repo_path: str) -> bool:
        """Checks if cache is older than the newest file in repo."""
        try:
            cache_time = cache_path.stat().st_mtime
            for root, dirs, files in os.walk(repo_path):
                # Skip vendor/cache dirs
                dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", ".venv", "venv"}]
                for file in files:
                    if file.endswith((".py", ".js", ".ts", ".rs", ".go")):
                        file_path = os.path.join(root, file)
                        file_time = os.path.getmtime(file_path)
                        if file_time > cache_time:
                            log.debug(f"Cache stale: {file} modified after cache")
                            return True
            return False
        except Exception as e:
            log.debug(f"Cache staleness check failed: {e}")
            return True

    def _system_prompt(self) -> str:
        base = """Eres un asistente de programacion experto. Trabajas DENTRO de un repositorio local YA accesible en la ruta actual.
NUNCA pidas al usuario la ruta del proyecto, que lo clone, ni asumas que no tienes acceso: SIEMPRE usa las herramientas directamente sobre el repo.
No recibes contexto del codigo de antemano: lo recuperas TU MISMO con las herramientas, pidiendo solo lo minimo necesario.
Si dices que vas a hacer algo (editar, leer, ejecutar), HAZLO en el mismo turno con la herramienta correspondiente — no lo anuncies y pares.

Herramientas estructurales (PREFIERELAS — devuelven simbolos exactos, no archivos enteros):
- find_symbol: localiza funciones/clases/metodos por nombre. EMPIEZA SIEMPRE por aqui.
- read_symbol: lee el cuerpo de UNA funcion/clase (firma+docstring+codigo). Usalo en vez de read_file para ver una funcion.
- who_calls / callees: quien llama a un simbolo / a quien llama (grafo de dependencias).
- impact: que se romperia si cambias un simbolo (callers transitivos).
- list_by_kind: lista TODOS los simbolos de un tipo (endpoint, class, method, function...). Para preguntas agregadas ('cuantos endpoints hay').
- search_code: grep de texto cuando no sabes el nombre exacto (devuelve file:line).

Herramientas de archivo/edicion:
- read_file: solo para archivos pequenos o un rango (start_line/end_line). Archivos grandes se capan.
- write_file / replace_in_file: editar (replace_in_file para cambios pequenos, old_string exacto y unico).
- list_files, execute_command, run_tests, git_diff.

Reglas:
- Para entender/explicar codigo: find_symbol -> read_symbol -> who_calls/callees. NO leas archivos enteros.
- NO modifiques un simbolo sin leerlo antes (read_symbol o read_file con rango).
- Usa run_tests para verificar. Cambios minimos y precisos.
- Cuando tengas la informacion suficiente, DA LA RESPUESTA FINAL completa. No pidas mas herramientas de las necesarias.
- Si no sabes algo, dilo. No inventes.
- Para execute_command en Windows: usa comandos PowerShell o python.
- Si recibes imagenes, analizalas visualmente: colores, layout, tipografia, jerarquia."""
        # Verbosity steering se inyecta condicionalmente en run()/stream_run()
        # (solo tasks NO-amplitud) — ver _maybe_inject_verbosity.
        return base


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


_LOOP_BLOCK_THRESHOLD = 3   # bloquea solo a la 3ª llamada IDÉNTICA (permite reintentos legítimos)


def _loop_key(name: str, args: dict) -> str:
    """Clave de detección de bucles: tool + args COMPLETOS y ordenados. Misma tool con
    args DISTINTOS → claves distintas (no se penaliza); solo la repetición exacta cuenta."""
    try:
        a = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except Exception:
        a = str(sorted(args.items())) if isinstance(args, dict) else str(args)
    return f"{name}|{a}"


def _assistant_tool_msg(text: str, tool_calls: list[dict], reasoning: str = "") -> dict:
    """Construye UN mensaje assistant con todos los tool_calls (spec OpenAI), args en JSON,
    y reasoning_content si el modelo lo exige (DeepSeek V4 thinking lo rechaza si falta).
    Cada tc debe traer su id estable en `_id`."""
    msg = {
        "role": "assistant",
        "content": text or "",
        "tool_calls": [{"id": tc["_id"], "type": "function",
                        "function": {"name": tc["name"],
                                     "arguments": json.dumps(tc.get("args", {}))}}
                       for tc in tool_calls],
    }
    if reasoning:
        msg["reasoning_content"] = reasoning
    return msg


def _compact_messages(messages: list[dict], keep_last: int = 6) -> list[dict]:
    """Compacta historial preservando system + user original + ultimos mensajes.
    No separa assistant(con tool_calls) de sus tool messages."""
    if len(messages) <= keep_last + 2:
        return messages

    # Encontrar dónde cortar, respetando pares assistant+tool
    # Si la última sección contiene tool messages, asegurar que el assistant precedente esté incluido
    end_idx = len(messages)
    for i in range(len(messages) - 1, max(1, len(messages) - keep_last - 5), -1):
        if messages[i].get("role") == "tool" and i > 0:
            # Retroceder hasta encontrar el assistant con tool_calls
            for j in range(i - 1, 0, -1):
                if messages[j].get("role") == "assistant" and messages[j].get("tool_calls"):
                    end_idx = j  # Incluir desde este assistant
                    break
            break

    recent = messages[end_idx:]
    head = messages[:2]
    old_count = end_idx - 2

    if old_count > 0:
        # Cache alignment (Headroom): contenido del summary byte-estable (sin el
        # contador volátil) → no invalida el prompt cache en compactaciones repetidas.
        summary = {"role": "system", "content": "[Historial previo compactado para ahorrar tokens]"}
        return head + [summary] + recent
    return messages
