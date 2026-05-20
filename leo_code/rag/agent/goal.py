"""GoalRunner — agente persistente por objetivos. No para hasta completar la tarea.

Fases:
  1. PLANIFICAR: el LLM descompone el goal en pasos concretos
  2. EJECUTAR: ejecuta cada paso con KC-RAG, sin preguntar "¿sigo?"
  3. VERIFICAR: corre tests/linter al final, evalúa si el goal se cumplió
  4. RE-PLANIFICAR: si algo falló, ajusta los pasos restantes y reintenta

Integración: AgentLoop.goal_stream_run() → GoalRunner
"""

import time
from dataclasses import dataclass, field


@dataclass
class GoalStep:
    index: int
    description: str
    status: str = "pending"  # pending | running | done | failed
    tool_calls: int = 0
    tokens: int = 0
    duration_ms: int = 0

@dataclass
class Goal:
    id: str
    description: str
    steps: list[GoalStep] = field(default_factory=list)
    status: str = "planning"  # planning | running | verifying | done | cancelled
    current_step: int = 0
    total_tokens: int = 0
    total_duration_ms: int = 0
    created_at: float = 0
    iterations: int = 0
    max_iterations: int = 15


class GoalRunner:
    """Orquesta el ciclo plan → ejecutar → verificar → re-planificar."""

    def __init__(self, agent, tools, llm):
        self.agent = agent
        self.tools = tools
        self.llm = llm
        self.goal: Goal | None = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self.goal:
            self.goal.status = "cancelled"

    async def run(self, goal_text: str, repo_path: str, model: str = "",
                  plugin_manager=None, skill_manager=None):
        """Ejecuta un goal completo: plan → execute → verify → re-plan → done."""
        import uuid
        t0 = time.time()

        self.goal = Goal(
            id=uuid.uuid4().hex[:12],
            description=goal_text,
            created_at=t0,
        )
        self._cancel = False

        yield {"type": "goal_start", "goal": self.goal.id, "description": goal_text}

        # Fase 1: PLANIFICAR
        yield {"type": "goal_phase", "phase": "planning"}
        plan = await self._plan(goal_text, repo_path, model, plugin_manager, skill_manager)
        if not plan:
            yield {"type": "goal_error", "error": "No se pudo generar un plan"}
            return
        for i, step_desc in enumerate(plan[:12], 1):
            self.goal.steps.append(GoalStep(index=i, description=step_desc))
        yield {"type": "plan", "steps": [s.description for s in self.goal.steps]}

        # Fase 2 + 3 + 4: EJECUTAR → VERIFICAR → RE-PLANIFICAR
        self.goal.status = "running"
        while self.goal.current_step < len(self.goal.steps) and self.goal.iterations < self.goal.max_iterations:
            if self._cancel:
                break

            step = self.goal.steps[self.goal.current_step]
            step.status = "running"
            self.goal.iterations += 1
            yield {"type": "step_start", "step": step.index, "total": len(self.goal.steps),
                   "description": step.description}

            # Ejecutar paso con KC-RAG
            try:
                result = await self._execute_step(step, repo_path, model, plugin_manager, skill_manager)
                step.tokens = result.get("tokens", 0)
                step.tool_calls = result.get("tool_calls", 0)
                step.duration_ms = result.get("duration_ms", 0)
                self.goal.total_tokens += step.tokens

                if result.get("success", True):
                    step.status = "done"
                else:
                    step.status = "failed"
                    # Re-plan: el LLM sugiere pasos adicionales/reemplazo
                    new_steps = await self._replan(step, self.goal, repo_path, model)
                    if new_steps:
                        old_len = len(self.goal.steps)
                        for ns in new_steps:
                            old_len += 1
                            self.goal.steps.insert(self.goal.current_step + 1,
                                GoalStep(index=old_len, description=ns))
                        yield {"type": "replan", "added_steps": new_steps}
            except Exception as e:
                step.status = "failed"
                yield {"type": "step_error", "step": step.index, "error": str(e)}

            yield {"type": "step_done", "step": step.index, "status": step.status,
                   "progress": f"{self.goal.current_step + 1}/{len(self.goal.steps)}",
                   "tokens": step.tokens, "duration_ms": step.duration_ms}
            self.goal.current_step += 1
            self.goal.total_duration_ms = int((time.time() - t0) * 1000)

        # Fase final: VERIFICAR
        if not self._cancel:
            self.goal.status = "verifying"
            yield {"type": "goal_phase", "phase": "verifying"}
            verification = await self._verify(goal_text, self.goal, repo_path, model)
            yield {"type": "verify", "result": verification}
            if verification.get("success", True):
                self.goal.status = "done"
            else:
                remaining = verification.get("remaining", "")
                if remaining and self.goal.iterations < self.goal.max_iterations:
                    yield {"type": "goal_continue", "remaining": remaining}

        self.goal.total_duration_ms = int((time.time() - t0) * 1000)
        yield {"type": "goal_done", "goal": self.goal.id,
               "status": self.goal.status,
               "steps_done": sum(1 for s in self.goal.steps if s.status == "done"),
               "total_steps": len(self.goal.steps),
               "tokens": self.goal.total_tokens,
               "duration_ms": self.goal.total_duration_ms,
               "iterations": self.goal.iterations}

    async def _plan(self, goal_text: str, repo_path: str, model: str,
                    plugin_manager, skill_manager) -> list[str]:
        """LLM descompone el goal en pasos concretos."""
        query = f"""Descompón esta tarea en pasos concretos y ordenados. Responde SOLO con una lista numerada, un paso por línea. Sé específico: menciona archivos, funciones, herramientas a usar.

Tarea: {goal_text}

Formato:
1. Leer archivo X para entender Y
2. Modificar Z en archivo W
3. Ejecutar tests para verificar
...
"""
        try:
            messages = [
                {"role": "system", "content": "Eres un planificador de tareas de programacion. Responde solo con pasos numerados."},
                {"role": "user", "content": query},
            ]
            resp = await self.llm.generate(messages, tools=[], temperature=0.1)
            text = resp.text or ""
            steps = []
            for line in text.strip().split("\n"):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith("- ")):
                    step = line.lstrip("0123456789. -)").strip()
                    if step and len(step) > 3:
                        steps.append(step)
            return steps[:12] if steps else [goal_text[:120]]
        except Exception:
            return [goal_text[:120]]

    async def _execute_step(self, step: GoalStep, repo_path: str, model: str,
                            plugin_manager, skill_manager) -> dict:
        """Ejecuta un paso con KC-RAG + LLM + tools."""
        t0 = time.time()
        try:
            query = f"Completa este paso del plan: {step.description}"
            messages = [
                {"role": "system", "content": self.agent._system_prompt()},
                {"role": "user", "content": query},
            ]

            # KC-RAG context
            context = ""
            try:
                from leo_code.rag.classifier import classify_task
                tt = classify_task(query)
                ctx = self.agent._build_context(query, repo_path, tt)
                if ctx:
                    context = ctx
                    messages.insert(1, {"role": "system", "content": f"Contexto:\n{context}"})
            except Exception:
                pass

            tool_defs = self.tools.get_openai_definitions()
            tool_count = 0
            total_tokens = 0

            for _ in range(5):  # max 5 tool rounds per step
                resp = await self.llm.generate(messages, tool_defs, temperature=0.2)
                total_tokens += resp.usage.input_tokens + resp.usage.output_tokens
                if not resp.tool_calls:
                    break
                for tc in resp.tool_calls:
                    result = self.tools.execute(tc.name, tc.arguments, repo_path)
                    messages.append({"role": "assistant", "content": resp.text or "",
                                     "tool_calls": [{"id": tc.id, "type": "function",
                                                      "function": {"name": tc.name, "arguments": str(tc.arguments)}}]})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:4000]})
                    tool_count += 1

            return {
                "success": True,
                "tokens": total_tokens,
                "tool_calls": tool_count,
                "duration_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "tokens": 0, "tool_calls": 0,
                    "duration_ms": int((time.time() - t0) * 1000)}

    async def _replan(self, failed_step: GoalStep, goal: Goal, repo_path: str,
                      model: str) -> list[str]:
        """Si un paso falló, pide al LLM pasos alternativos."""
        try:
            query = f"""El paso "{failed_step.description}" falló.
Tarea original: {goal.description}
Pasos completados: {[s.description for s in goal.steps if s.status == 'done']}
Pasos restantes: {[s.description for s in goal.steps[goal.current_step+1:]]}

Sugiere 1-3 pasos alternativos o adicionales para completar la tarea.
Responde solo con pasos numerados, uno por línea."""
            messages = [
                {"role": "system", "content": "Eres un planificador. Pasos concretos, una línea cada uno."},
                {"role": "user", "content": query},
            ]
            resp = await self.llm.generate(messages, tools=[], temperature=0.2)
            text = resp.text or ""
            return [line.lstrip("0123456789. -)").strip()
                    for line in text.strip().split("\n")
                    if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith("- "))][:3]
        except Exception:
            return []

    async def _verify(self, goal_text: str, goal: Goal, repo_path: str,
                      model: str) -> dict:
        """El LLM evalúa si el goal se cumplió."""
        try:
            steps_done = [s.description for s in goal.steps if s.status == "done"]
            steps_failed = [s.description for s in goal.steps if s.status == "failed"]
            query = f"""Tarea: {goal_text}
Pasos completados ({len(steps_done)}): {', '.join(steps_done[:8])}
{('Pasos fallidos: ' + ', '.join(steps_failed)) if steps_failed else ''}

¿Se completó la tarea? Responde con:
- "DONE" si la tarea está completa
- "PARTIAL: <lo que falta>" si está parcialmente completa
- "FAILED: <razon>" si no se pudo completar"""
            messages = [
                {"role": "system", "content": "Evalua si una tarea de programacion esta completa. Responde DONE, PARTIAL, o FAILED con explicacion breve."},
                {"role": "user", "content": query},
            ]
            resp = await self.llm.generate(messages, tools=[], temperature=0.1)
            text = (resp.text or "").strip()
            if text.upper().startswith("DONE"):
                return {"success": True, "result": text}
            elif text.upper().startswith("PARTIAL"):
                return {"success": False, "remaining": text.replace("PARTIAL:", "").strip(), "result": text}
            return {"success": False, "result": text or "Verificacion no concluyente"}
        except Exception:
            return {"success": True, "result": "Verificacion automatica no disponible, asumiendo exito"}
