"""Session compactor — compacta historial preservando referencias a código.

Estrategia: identifica funciones/archivos mencionados en la conversación,
los mantiene como contexto estructural, y resume el resto del diálogo.
"""


def compact_history(messages: list[dict], max_messages: int = 30) -> list[dict]:
    """Compacta historial preservando contexto de código."""
    if len(messages) <= max_messages:
        return messages

    # Mantener los últimos max_messages - 2
    recent = messages[-(max_messages - 2):]

    # Extraer referencias a código del historial antiguo
    code_refs = _extract_code_refs(messages[:-len(recent)])

    # Construir resumen
    summary_parts = ["[Resumen de conversacion anterior]"]
    if code_refs.get("files"):
        summary_parts.append(f"Archivos mencionados: {', '.join(sorted(code_refs['files'])[:10])}")
    if code_refs.get("functions"):
        summary_parts.append(f"Funciones discutidas: {', '.join(sorted(code_refs['functions'])[:10])}")
    if code_refs.get("actions"):
        summary_parts.append(f"Acciones realizadas: {'; '.join(code_refs['actions'][:5])}")

    summary = [{"role": "system", "content": "\n".join(summary_parts)}]
    return summary + recent


def _extract_code_refs(messages: list[dict]) -> dict:
    """Extrae referencias a archivos, funciones y acciones del historial."""
    import re
    refs: dict[str, set] = {"files": set(), "functions": set(), "actions": set()}

    file_pattern = re.compile(r"(?:en|in|archivo|file|path)[\s:]+([\w./-]+\.[\w]+)")
    func_pattern = re.compile(r"(?:función|funcion|function|def|class)\s+[`'\x22]?(\w+)[`'\x22]?")

    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(item.get("text", "") for item in content if isinstance(item, dict))

        for match in file_pattern.finditer(str(content)):
            refs["files"].add(match.group(1))
        for match in func_pattern.finditer(str(content)):
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
