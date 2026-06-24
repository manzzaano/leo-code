"""Session compactor — compacta historial preservando referencias a código.

Estrategia (AgentScope + ECC):
- Trigger por TOKENS reales (trigger_ratio de la ventana) cuando se pasa `max_tokens`;
  si no, fallback por número de mensajes (compat retro).
- Reserva los últimos mensajes intactos (reserve_ratio) → prefijo + recientes byte-estables.
- Resume el resto en un bloque system estructurado. Por defecto el resumen es
  determinista (refs de código extraídas); con un `summarizer` LLM opcional produce
  el resumen de 5 campos (task overview / current state / discoveries / next steps /
  context to preserve).
"""

from __future__ import annotations

from typing import Callable, Optional

from leo_code.core.tokens import count_tokens

_SUMMARY_HEADER = "[Resumen de conversacion anterior]"


def _msg_text(m: dict) -> str:
    content = m.get("content", "")
    if isinstance(content, list):
        return " ".join(item.get("text", "") for item in content if isinstance(item, dict))
    return str(content)


def _history_tokens(messages: list[dict]) -> int:
    return sum(count_tokens(_msg_text(m)) for m in messages)


def compact_history(
    messages: list[dict],
    max_messages: int = 30,
    max_tokens: Optional[int] = None,
    trigger_ratio: float = 0.7,
    reserve_ratio: float = 0.4,
    summarizer: Optional[Callable[[list[dict]], str]] = None,
) -> list[dict]:
    """Compacta historial preservando contexto de código.

    - Si `max_tokens` se da: dispara cuando los tokens superan `trigger_ratio·max_tokens`
      y reserva los últimos `reserve_ratio·max_tokens` intactos.
    - Si no: dispara por número de mensajes (>`max_messages`), reservando los últimos.
    Devuelve el MISMO objeto si no hace falta compactar (cache-friendly).
    """
    if not messages:
        return []

    # ── Decidir si compactar y cuántos mensajes recientes reservar ──
    if max_tokens is not None:
        total = _history_tokens(messages)
        if total <= trigger_ratio * max_tokens:
            return messages
        reserve_budget = int(reserve_ratio * max_tokens)
        recent: list[dict] = []
        acc = 0
        for m in reversed(messages):
            t = count_tokens(_msg_text(m))
            if acc + t > reserve_budget and recent:
                break
            recent.insert(0, m)
            acc += t
        split = len(messages) - len(recent)
    else:
        if len(messages) <= max_messages:
            return messages
        recent = messages[-(max_messages - 2):]
        split = len(messages) - len(recent)

    old = messages[:split]
    if not old:
        return messages

    # ── Construir el resumen del bloque antiguo ──
    if summarizer is not None:
        try:
            body = summarizer(old)
        except Exception:
            body = _deterministic_summary(old)
    else:
        body = _deterministic_summary(old)

    summary = {"role": "system", "content": f"{_SUMMARY_HEADER}\n{body}".rstrip()}
    return [summary] + recent


def _deterministic_summary(messages: list[dict]) -> str:
    """Resumen estructurado y determinista a partir de refs de código extraídas."""
    refs = _extract_code_refs(messages)
    lines: list[str] = [f"Mensajes omitidos: {len(messages)}"]
    if refs.get("files"):
        lines.append(f"Archivos mencionados: {', '.join(sorted(refs['files'])[:10])}")
    if refs.get("functions"):
        lines.append(f"Funciones discutidas: {', '.join(sorted(refs['functions'])[:10])}")
    if refs.get("actions"):
        lines.append(f"Acciones realizadas: {'; '.join(sorted(refs['actions'])[:5])}")
    return "\n".join(lines)


def _extract_code_refs(messages: list[dict]) -> dict:
    """Extrae referencias a archivos, funciones y acciones del historial."""
    import re
    refs: dict[str, set] = {"files": set(), "functions": set(), "actions": set()}

    file_pattern = re.compile(r"(?:en|in|archivo|file|path)[\s:]+([\w./-]+\.[\w]+)")
    func_pattern = re.compile(r"(?:función|funcion|function|def|class)\s+[`'\x22]?(\w+)[`'\x22]?")

    for m in messages:
        content = _msg_text(m)
        for match in file_pattern.finditer(content):
            refs["files"].add(match.group(1))
        for match in func_pattern.finditer(content):
            name = match.group(1)
            if name not in ("if", "for", "while", "return", "new", "class"):
                refs["functions"].add(name)

    actions = {"read_file": "archivos leidos", "write_file": "archivos escritos",
                "replace_in_file": "cambios realizados", "run_tests": "tests ejecutados",
                "execute_command": "comandos ejecutados", "gh_pr_create": "PR creado"}
    for m in messages:
        tcs = m.get("tool_calls", [])
        for tc in tcs if isinstance(tcs, list) else []:
            name = tc.get("function", {}).get("name", tc.get("name", ""))
            if name in actions:
                refs["actions"].add(actions[name])

    return refs
