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
from leo_code.rag.semantic_clustering import SemanticClusterer
from leo_code.rag.cluster_serializer import serialize_clusters

log = logging.getLogger("leo.agent")


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
        self._bm25 = None
        self._clusterer = None
        self._clusters = None
        self._conversation_history = None
        self._indexed_repos = set()
        self._recent_calls: set[str] = set()  # anti-loop
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
        if use_kc_rag:
            from leo_code.rag.classifier import classify_task
            t_c0 = time.perf_counter()
            task_type = classify_task(query)
            t_classify_ms = (time.perf_counter() - t_c0) * 1000
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
            resp = await self.llm.generate(messages, tool_defs, temperature=0.2)
            t_llm_ms += (time.perf_counter() - t_llm0) * 1000
            llm_iterations += 1
            total_tokens += resp.usage.input_tokens + resp.usage.output_tokens
            text = resp.text or ""
            all_text += text

            if not resp.tool_calls:
                if session_id:
                    self._persist_turn(session_id, query, text, model, total_tokens)
                # Save to conversation history
                if self._conversation_history and context:
                    self._conversation_history.save_conversation(query, context, total_tokens, iteration + 1)
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
            for tc, tc_data in zip(resp.tool_calls, all_tool_calls):
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except: args = {}
                call_key = f"{tc.name}:{str(args)[:80]}"
                if call_key in self._recent_calls:
                    messages.append({"role": "tool", "tool_call_id": tc_data["id"], "content": "[Llamada repetida]"})
                    continue
                self._recent_calls.add(call_key)
                self._tool_call_count += 1

                result = self.tools.execute(tc.name, args, repo_path)
                if len(result) > 800:
                    result = result[:800] + f"\n[truncado — usa search_code para detalles]"
                messages.append({"role": "tool", "tool_call_id": tc_data["id"], "content": result[:1000]})
                total_tokens += len(result) // 4

            # ABORT: si llegamos a muchas iteraciones, usa el texto acumulado
            if iteration >= 8 and all_text.strip():
                if session_id:
                    self._persist_turn(session_id, query, all_text, model, total_tokens)
                duration_ms = int((time.time() - t0) * 1000)
                get_metrics().record_query(total_tokens, duration_ms,
                                          t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
                log.info(f"query aborted at iter {iteration} | tokens={total_tokens} ms={duration_ms}")
                return {"respuesta": all_text, "total_tokens": total_tokens,
                        "iterations": iteration + 1,
                        "duration_ms": duration_ms}
            elif iteration >= 8:
                messages.append({"role": "system", "content": "DA TU RESPUESTA FINAL AHORA. NO PIDAS MAS HERRAMIENTAS."})

        duration_ms = int((time.time() - t0) * 1000)
        get_metrics().record_query(total_tokens, duration_ms,
                                  t_index_ms, t_classify_ms, t_search_ms, t_compress_ms, t_llm_ms)
        log.warning(f"query max_iterations reached | iterations={self.max_iterations} tokens={total_tokens} ms={duration_ms}")
        return {"respuesta": all_text or f"[No completado en {self.max_iterations} iteraciones. {self._tool_call_count} tools ejecutadas.]",
                "total_tokens": total_tokens, "iterations": self.max_iterations,
                "duration_ms": duration_ms}

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
        if use_kc_rag:
            from leo_code.rag.classifier import needs_code_context, classify_task
            t_c0 = time.perf_counter()
            task_type = classify_task(query)
            t_classify_ms = (time.perf_counter() - t_c0) * 1000
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
        all_text = ""
        llm_iterations = 0

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
            t_llm0 = time.perf_counter()
            async for chunk in self.llm.stream(messages, tool_defs):
                if self.interrupt:
                    break
                if isinstance(chunk, str):
                    text += chunk
                    all_text += chunk
                    yield {"type": "token", "text": chunk}
                elif isinstance(chunk, dict) and chunk.get("type") == "tool_call":
                    tool_calls.append(chunk)
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

            # Execute tools
            for tc in tool_calls:
                args = tc.get("args", {})
                tc_id = tc.get("id", f"call_{iteration}_{hash(tc['name']) % 10000}")

                # Permission check
                if self.perms:
                    allowed, reason = self.perms.check(tc["name"], args)
                    if not allowed:
                        yield {"type": "tool_start", "name": tc["name"], "args": args}
                        yield {"type": "tool_result", "name": tc["name"], "output": f"[Bloqueado: {reason}]"}
                        messages.append({"role": "assistant", "content": text or "", "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": tc["name"], "arguments": str(args)}}]})
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"[Bloqueado: {reason}]"})
                        continue

                # Loop detection
                call_key = f"{tc['name']}:{str(args)[:80]}"
                if call_key in self._recent_calls:
                    yield {"type": "tool_start", "name": tc["name"], "args": args}
                    yield {"type": "tool_result", "name": tc["name"], "output": f"[Llamada repetida a {tc['name']} — busca otra estrategia]"}
                    messages.append({"role": "assistant", "content": text or "", "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": tc["name"], "arguments": str(args)}}]})
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"[Llamada repetida]"})
                    continue
                self._recent_calls.add(call_key)
                self._tool_call_count += 1

                yield {"type": "tool_start", "name": tc["name"], "args": args}
                result = self.tools.execute(tc["name"], args, repo_path)
                # Trim resultes largos
                if len(result) > 800:
                    result = result[:800] + f"\n[truncado — usa search_code para detalles]"
                yield {"type": "tool_result", "name": tc["name"], "output": result}
                messages.append({"role": "assistant", "content": text or "", "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": tc["name"], "arguments": str(args)}}]})
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result[:1000]})
                total_tokens += len(result) // 4

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
        """Construye contexto vía KC-RAG adaptativo: indexer → classify → Qdrant → compress.

        Returns: (context_str, timings_dict)
        """
        timings = {"t_index_ms": 0, "t_search_ms": 0, "t_compress_ms": 0}
        try:
            if repo_path not in self._indexed_repos:
                t_idx0 = time.perf_counter()
                self._ensure_indexed(repo_path)
                timings["t_index_ms"] = (time.perf_counter() - t_idx0) * 1000

            caps = self._indexer.get_capsules()
            if not caps:
                return "", timings

            from leo_code.rag.classifier import get_budget
            budget = get_budget(query)

            t_search0 = time.perf_counter()
            # Hybrid retrieval: exact match + vector + BM25 + RRF
            exact = _exact_match(query, list(caps.values()))
            semantic = [caps[rid] for rid in self._vector_store.search(query, top_k=15) if rid in caps]
            bm25_results = self._bm25.search(query, top_k=15) if self._bm25 else []
            top_caps = _rrf_fuse(exact, semantic, bm25_results, caps)
            timings["t_search_ms"] = (time.perf_counter() - t_search0) * 1000

            t_comp0 = time.perf_counter()

            # Use hierarchical cluster serialization if available
            if self._clusters and top_caps:
                # Find clusters containing top_caps
                cluster_ids = set()
                for cap in top_caps:
                    cid = self._clusterer.capsule_to_cluster.get(cap.id)
                    if cid is not None:
                        cluster_ids.add(cid)

                # Get clusters and serialize hierarchically
                relevant_clusters = [self._clusters[cid] for cid in sorted(cluster_ids) if cid < len(self._clusters)]
                context = serialize_clusters(relevant_clusters)
            else:
                # Fallback to compression
                from leo_code.rag.compressor import compress
                context = compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type)

            timings["t_compress_ms"] = (time.perf_counter() - t_comp0) * 1000

            # Load previous conversation context if available
            if self._conversation_history:
                prev = self._conversation_history.load_previous_contexts(query, limit=2)
                if prev.get("accumulated_context"):
                    # Prepend previous context with separator
                    context = f"{prev['accumulated_context']}\n--- Current Query ---\n{context}"

            return context, timings
        except Exception as e:
            log.exception(f"KC-RAG error: {e}")
            return f"[KC-RAG no disponible: {e}]", timings

    def _ensure_indexed(self, repo_path: str):
        from leo_code.rag.indexer import Indexer
        from leo_code.rag.vector_store import VectorStore
        from pathlib import Path

        cache_dir = Path(repo_path) / ".leo-code"
        cache_path = cache_dir / "kc_index.json.gz"

        self._indexer = Indexer()

        # Try to load from cache if fresh
        if cache_path.exists() and not self._is_cache_stale(cache_path, repo_path):
            log.debug(f"Loading index from cache: {cache_path}")
            self._indexer.load(str(cache_path))
        else:
            # Build and save
            log.debug(f"Building index for {repo_path}")
            self._indexer.build(repo_path, verbose=False)
            # Save for next time
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._indexer.save(str(cache_path))

        self._vector_store = VectorStore(
            collection_name=f"kc_agent_{hash(repo_path) % 10000}",
            path="./cache/qdrant_agent"
        )
        caps_list = list(self._indexer.get_capsules().values())
        self._vector_store.add(caps_list)

        # Build BM25 index
        from leo_code.rag.bm25 import BM25Index
        self._bm25 = BM25Index()
        self._bm25.add(caps_list)

        # Initialize semantic clustering
        from leo_code.rag.encoder import Encoder
        encoder = Encoder()
        self._clusterer = SemanticClusterer(encoder)

        # Encode all capsules and cluster them
        embeddings = encoder.encode_batch([f"{c.name} {c.docstring or ''}" for c in caps_list])
        self._clusters = self._clusterer.cluster(caps_list, embeddings)

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
        summary = {"role": "system", "content": f"[Historial compactado: {old_count} mensajes omitidos para ahorrar tokens]"}
        return head + [summary] + recent
    return messages


def _exact_match(query: str, capsules: list) -> list:
    """Exact match: busca cápsulas por nombre/path.

    Tokeniza query (palabras >=4 chars + sub-partes), busca en names/paths.
    Devuelve lista priorizando matches exactos de nombre.
    """
    import re
    # Tokenizar: palabras >= 4 chars (matches server.py)
    tokens = set()
    for word in re.findall(r'\w{4,}', query.lower()):
        tokens.add(word)
        # También agregar sub-partes separadas por guion/underscore
        for part in word.split('_'):
            if len(part) >= 4:
                tokens.add(part)
        for part in word.split('-'):
            if len(part) >= 4:
                tokens.add(part)

    if not tokens:
        return []

    matches = []
    for cap in capsules:
        cap_name_lower = cap.name.lower()
        cap_path_stem = cap.file_path.lower().split('/')[-1].split('.')[0]

        # Prioridad: nombre exacto > múltiples tokens > single token
        matched_tokens = [t for t in tokens if t in cap_name_lower]
        if matched_tokens:
            # Más tokens matcheados = mayor prioridad
            priority = 3 + len(matched_tokens)
            matches.append((priority, cap))
        else:
            # Path match: prioridad baja
            matched_path = [t for t in tokens if t in cap_path_stem]
            if matched_path:
                matches.append((1 + len(matched_path), cap))

    # Ordenar por prioridad, devolver cápsulas únicas (max 20)
    matches.sort(key=lambda x: -x[0])
    seen = set()
    result = []
    for _, cap in matches:
        if cap.id not in seen:
            seen.add(cap.id)
            result.append(cap)
            if len(result) >= 20:
                break
    return result


def _rrf_fuse(exact: list, semantic: list, bm25_results: list, caps_dict: dict) -> list:
    """RRF fusion: combina exact match + vector + BM25 con reciprocal rank fusion.

    score = sum(1 / (k + rank + 1)) para cada ranking.
    k = 60 (matches server.py).
    Devuelve top-20 cápsulas ordenadas por score RRF.
    """
    fused_scores = {}
    k = 60

    # Exact match scores
    for rank, cap in enumerate(exact):
        fused_scores[cap.id] = fused_scores.get(cap.id, 0) + 1 / (k + rank + 1)

    # Semantic (vector) scores
    for rank, cap in enumerate(semantic):
        fused_scores[cap.id] = fused_scores.get(cap.id, 0) + 1 / (k + rank + 1)

    # BM25 scores
    for rank, bm25_result in enumerate(bm25_results):
        if bm25_result.capsule_id in caps_dict:
            fused_scores[bm25_result.capsule_id] = fused_scores.get(bm25_result.capsule_id, 0) + 1 / (k + rank + 1)

    # Ordenar por score y devolver cápsulas
    sorted_ids = sorted(fused_scores.items(), key=lambda x: -x[1])
    result = []
    for cap_id, _ in sorted_ids[:20]:
        if cap_id in caps_dict:
            result.append(caps_dict[cap_id])

    return result
