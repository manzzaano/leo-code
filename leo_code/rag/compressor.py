"""Compressor adaptativo: construye el prompt según el tipo de tarea.

Estrategias:
- code_gen: estructura de directorios y archivos del repo
- code_edit: función target + dependencias directas (sin cuerpos completos)
- code_query: primer resultado cuerpo completo, resto firma+docstring
- refactor: target + callers + callees (BFS depth 1)
- search: mini-mapa ligero con flags ✓doc/✗doc
- debug: función target + callers + callees depth 2 + cuerpos completos
- test_gen: función target + tests existentes en el repo como referencia
- review: top funciones para revisión de código
- optimize: cuerpos completos para análisis de performance
- audit: top funciones con foco en patrones de seguridad
- onboard: mapa de alto nivel del proyecto (estructura + entrypoints)
- no_code: solo cápsulas tipo documento
"""

from leo_code.core.parser import Capsule
from leo_code.core.context import serialize_context


def compress(
    top_capsules: list[Capsule],
    all_capsules: list[Capsule],
    budget_tokens: int = 1500,
    task_type: str = "code_query",
    dir_filter: set[str] | None = None,
) -> str:
    """Compresión adaptativa según tipo de tarea."""

    if task_type == "no_code":
        doc_caps = [c for c in top_capsules if c.type == "document"]
        if doc_caps:
            return _compress_query(doc_caps, budget_tokens)
        return _compress_query(top_capsules, max(budget_tokens, 800))

    # Para code tasks: excluir docs de dominio del contexto
    top_capsules = [c for c in top_capsules if c.type != "document"]
    all_capsules  = [c for c in all_capsules  if c.type != "document"]

    if task_type == "code_gen":
        # code_gen queries need actual code content (signatures, bodies) not just directory structure
        return _compress_query(top_capsules, budget_tokens)

    if task_type == "code_edit":
        return _compress_code_edit(top_capsules)

    if task_type == "search":
        return _compress_search(top_capsules, all_capsules, budget_tokens, dir_filter)

    if task_type == "refactor":
        return _compress_refactor(top_capsules, all_capsules)

    if task_type == "debug":
        return _compress_debug(top_capsules, all_capsules)

    if task_type == "test_gen":
        return _compress_test_gen(top_capsules, all_capsules)

    if task_type == "review":
        return _compress_review(top_capsules, all_capsules)

    if task_type == "optimize":
        return _compress_optimize(top_capsules, all_capsules)

    if task_type == "audit":
        return _compress_audit(top_capsules, all_capsules)

    if task_type == "onboard":
        return _compress_onboard(all_capsules)

    return _compress_query(top_capsules, budget_tokens)


def _compress_code_gen(all_capsules: list[Capsule]) -> str:
    """Solo estructura de directorios y archivos, sin contenido de código."""
    dirs = set()
    files = {}

    for c in all_capsules:
        parts = c.file_path.replace("\\", "/").split("/")
        for i in range(len(parts) - 1):
            dirs.add("/".join(parts[:i+1]))
        if c.file_path not in files:
            files[c.file_path] = c.language

    lines = ["Estructura del repositorio:"]
    for d in sorted(dirs):
        lines.append(f"  {d}/")
    for f in sorted(files):
        lines.append(f"  {f} ({files[f]})")

    lines.append(f"\nTotal: {len(files)} archivos, {len(all_capsules)} capsulas")
    lines.append("Usa search_code para explorar el codigo si necesitas detalles.")

    return "\n".join(lines)


def _compress_code_edit(top_capsules: list[Capsule]) -> str:
    """Función target + imports. Sin cuerpos completos."""
    nodes = []
    seen = set()

    for c in top_capsules[:5]:
        if c.type in ("function", "class") and c.name not in seen:
            seen.add(c.name)
            nodes.append({
                "id": c.id, "name": c.name, "type": c.type,
                "properties": {
                    "signature": c.signature,
                    "file_path": c.file_path,
                    "docstring": c.docstring or "",
                    "parametros": c.properties.get("parametros", ""),
                    "lineas": c.properties.get("lineas", c.end_line - c.start_line + 1),
                },
            })

    if not nodes:
        return ""

    context = serialize_context(nodes)
    context += "\n\nUsa read_file para ver el contenido completo antes de modificar."
    return context


def _compress_query(top_capsules: list[Capsule], budget_tokens: int) -> str:
    """Top-N adaptativo: primer resultado con cuerpo completo, el resto con firma+docstring."""
    if not top_capsules:
        return ""

    char_budget = budget_tokens * 4
    parts: list[str] = []
    total_chars = 0
    seen: set[str] = set()

    for i, c in enumerate(top_capsules):
        if c.name in seen:
            continue
        seen.add(c.name)

        # Primera cápsula relevante: incluir cuerpo completo si cabe
        if i == 0 and c.content and c.type in ("function", "class", "document", "file_header"):
            if c.type == "document":
                body_text = f"[{c.name}|doc] {c.file_path}\n{c.content}"
            elif c.type == "file_header":
                body_text = f"[{c.name}|file_header] {c.file_path}\n```python\n{c.content}\n```"
            else:
                body_text = f"[{c.name}|{c.type}] {c.file_path}\n```\n{c.content}\n```"
            if total_chars + len(body_text) <= char_budget:
                parts.append(body_text)
                total_chars += len(body_text)
                continue

        # Resto: firma + docstring + relaciones
        props = {
            "signature": c.signature,
            "file_path": c.file_path,
            "docstring": c.docstring or "",
        }
        if c.calls:
            props["calls"] = ", ".join(c.calls[:8])
        if c.imports:
            props["imports"] = ", ".join(c.imports[:8])
        if "parametros" in c.properties:
            props["parametros"] = c.properties["parametros"]
        if "tipo_retorno" in c.properties:
            props["tipo_retorno"] = c.properties["tipo_retorno"]
        node_chars = len(c.name) + len(c.signature or "") + len(c.docstring or "")
        if total_chars + node_chars > char_budget:
            break
        node = {"id": c.id, "name": c.name, "type": c.type, "properties": props}
        parts.append(serialize_context([node]))
        total_chars += node_chars

    if not parts:
        return ""

    context = "\n".join(parts)

    # Relaciones LLAMA — incluye todos los calls, no solo los que están en top_capsules
    edges = []
    for c in top_capsules:
        for call in c.calls[:5]:
            edges.append(f"[{c.name}]-[LLAMA]-[{call}]")

    if edges:
        context += "\n---\n" + "\n".join(edges[:5])

    return context


def _compress_refactor(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Target + callers + callees con firmas."""
    target = top_capsules[0] if top_capsules else None
    if not target:
        return ""

    nodes = [{
        "id": target.id, "name": target.name, "type": target.type,
        "properties": {
            "signature": target.signature,
            "file_path": target.file_path,
            "docstring": target.docstring or "",
            "parametros": target.properties.get("parametros", ""),
        },
    }]

    all_by_name = {c.name: c for c in all_capsules}
    for call in target.calls:
        if call in all_by_name:
            c = all_by_name[call]
            nodes.append({
                "id": c.id, "name": c.name, "type": c.type,
                "properties": {
                    "signature": c.signature,
                    "file_path": c.file_path,
                    "docstring": c.docstring or "",
                },
            })

    for c in all_capsules:
        if target.name in c.calls:
            nodes.append({
                "id": c.id, "name": c.name, "type": c.type,
                "properties": {
                    "signature": c.signature,
                    "file_path": c.file_path,
                    "docstring": c.docstring or "",
                },
            })

    return serialize_context(nodes)


def _compress_search(
    top_capsules: list[Capsule],
    all_capsules: list[Capsule],
    budget_tokens: int = 500,
    dir_filter: set[str] | None = None,
) -> str:
    """Mini-mapa ligero ordenado por relevancia. Trunca a budget_tokens."""
    # Filtrar por directorio si se especifica
    all_caps = all_capsules
    if dir_filter:
        all_caps = [
            c for c in all_capsules
            if any(f"/{d}/" in (c.file_path or "").lower().replace("\\", "/") for d in dir_filter)
        ]

    # Sección explícita: funciones SIN docstring (responde directamente la query de búsqueda)
    no_doc = [c for c in all_caps if not c.docstring and c.type in ("function", "class")]
    with_doc = [c for c in all_caps if c.docstring and c.type in ("function", "class")]
    summary: list[str] = [
        f"RESUMEN: {len(no_doc)} funciones/clases SIN docstring, {len(with_doc)} CON docstring.",
        "FUNCIONES SIN DOCSTRING:",
    ]
    for c in no_doc[:30]:
        summary.append(f"  ✗ [{c.type}] {c.name} — {c.file_path}")
    summary.append("")
    summary.append("Mapa completo por archivo:")

    # Archivos con capsulas top primero, luego el resto
    top_files = list(dict.fromkeys(c.file_path for c in top_capsules))
    by_file: dict[str, list[Capsule]] = {}
    for c in all_caps:
        by_file.setdefault(c.file_path, []).append(c)

    ordered_files = top_files + [f for f in sorted(by_file) if f not in top_files]

    map_lines: list[str] = []
    char_budget = budget_tokens * 4
    # El summary tiene su propio espacio; el file map usa el presupuesto restante
    # con un mínimo del 40% del total para garantizar que los flags ✓doc/✗doc aparezcan
    summary_chars = sum(len(s) for s in summary)
    map_budget = max(char_budget - summary_chars, int(char_budget * 0.4))
    total_chars = 0

    for file_path in ordered_files:
        caps = by_file.get(file_path, [])
        file_line = f"\n{file_path}:"
        if total_chars + len(file_line) > map_budget:
            break
        map_lines.append(file_line)
        total_chars += len(file_line)
        for c in caps[:10]:
            doc_flag = " ✓doc" if c.docstring else " ✗doc"
            cap_line = f"  [{c.type}] {c.name}{doc_flag}"
            if total_chars + len(cap_line) > map_budget:
                break
            map_lines.append(cap_line)
            total_chars += len(cap_line)

    map_lines.append(f"\nTotal: {len(all_caps)} capsulas en {len(by_file)} archivos")
    return "\n".join(summary + map_lines)


def _compress_debug(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Función target + cuerpo completo + callers + callees depth 2. Máximo contexto para debugging."""
    target = top_capsules[0] if top_capsules else None
    if not target:
        return _compress_query(top_capsules, 2500)

    all_by_name = {c.name: c for c in all_capsules}
    nodes = []

    # Target con cuerpo completo
    target_body = target.content or target.signature
    if target.content and len(target.content) > 3000:
        target_body = target.content[:3000] + "\n# ... [truncado]"
    nodes.append({
        "id": target.id, "name": target.name, "type": target.type,
        "properties": {
            "signature": target.signature,
            "file_path": target.file_path,
            "docstring": target.docstring or "",
            "content": target_body,
            "parametros": target.properties.get("parametros", ""),
            "tipo_retorno": target.properties.get("tipo_retorno", ""),
            "lineas": target.properties.get("lineas", target.end_line - target.start_line + 1),
        },
    })

    # Callees depth 1
    for call in target.calls:
        if call in all_by_name:
            c = all_by_name[call]
            nodes.append({
                "id": c.id, "name": c.name, "type": c.type,
                "properties": {
                    "signature": c.signature,
                    "file_path": c.file_path,
                    "docstring": c.docstring or "",
                    "parametros": c.properties.get("parametros", ""),
                },
            })

    # Callers que llaman al target
    callers = [c for c in all_capsules if target.name in c.calls]
    for c in callers[:5]:
        nodes.append({
            "id": c.id, "name": c.name, "type": c.type,
            "properties": {
                "signature": c.signature,
                "file_path": c.file_path,
                "docstring": c.docstring or "",
                "calls": ", ".join(c.calls[:8]),
            },
        })

    context = serialize_context(nodes)
    context += "\n\nDepura la funcion target. Revisa callers y callees. Usa read_file si necesitas mas contexto."
    return context


def _compress_test_gen(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Función target + tests existentes en el repo como referencia."""
    target = top_capsules[0] if top_capsules else None
    nodes = []

    if target:
        nodes.append({
            "id": target.id, "name": target.name, "type": target.type,
            "properties": {
                "signature": target.signature,
                "file_path": target.file_path,
                "docstring": target.docstring or "",
                "parametros": target.properties.get("parametros", ""),
                "tipo_retorno": target.properties.get("tipo_retorno", ""),
                "calls": ", ".join(target.calls[:8]),
            },
        })

    # Buscar tests existentes (funciones/clases con 'test' en nombre)
    test_caps = [c for c in all_capsules if "test" in c.name.lower() and c.type in ("function", "class")]
    if test_caps:
        nodes.append({
            "id": "__tests__", "name": "__tests__", "type": "section",
            "properties": {
                "descripcion": f"{len(test_caps)} tests existentes en el repo",
            },
        })
        for tc in test_caps[:8]:
            nodes.append({
                "id": tc.id, "name": tc.name, "type": tc.type,
                "properties": {
                    "signature": tc.signature,
                    "file_path": tc.file_path,
                    "docstring": tc.docstring or "",
                },
            })

    if not nodes:
        return ""

    context = serialize_context(nodes)
    context += "\n\nGenera tests para la funcion target. Usa los tests existentes como referencia de estilo."
    if test_caps:
        context += f" Hay {len(test_caps)} tests en el repo. Lee los mas relevantes con read_file."
    return context


def _compress_review(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Top funciones modificadas + estructura de dependencias para code review."""
    target = top_capsules[0] if top_capsules else None
    nodes = []

    if target:
        nodes.append({
            "id": target.id, "name": target.name, "type": target.type,
            "properties": {
                "signature": target.signature,
                "file_path": target.file_path,
                "docstring": target.docstring or "",
                "parametros": target.properties.get("parametros", ""),
                "tipo_retorno": target.properties.get("tipo_retorno", ""),
                "lineas": target.properties.get("lineas", target.end_line - target.start_line + 1),
                "calls": ", ".join(target.calls[:8]),
            },
        })

    all_by_name = {c.name: c for c in all_capsules}
    for c in top_capsules[1:10]:
        if c.type not in ("function", "class", "async_function", "test"):
            continue
        nodes.append({
            "id": c.id, "name": c.name, "type": c.type,
            "properties": {
                "signature": c.signature,
                "file_path": c.file_path,
                "docstring": c.docstring or "",
                "calls": ", ".join(c.calls[:5]),
            },
        })

    if not nodes:
        return ""

    context = serialize_context(nodes)
    context += "\n\nRevisa este codigo. Busca bugs, problemas de estilo, seguridad, y mejoras."
    return context


def _compress_optimize(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Funciones target con cuerpos para análisis de performance."""
    nodes = []
    seen = set()
    char_budget = 6000  # ~1500 tokens

    total = 0
    for c in top_capsules:
        if c.name in seen:
            continue
        if c.type not in ("function", "class", "async_function"):
            continue
        seen.add(c.name)
        body = c.content or ""
        if len(body) > 2000:
            body = body[:2000] + "\n# ... [truncado]"
        props = {
            "signature": c.signature,
            "file_path": c.file_path,
            "docstring": c.docstring or "",
            "lineas": c.properties.get("lineas", c.end_line - c.start_line + 1),
            "calls": ", ".join(c.calls[:8]),
        }
        if c.content:
            props["content"] = body
        node = {"id": c.id, "name": c.name, "type": c.type, "properties": props}
        node_chars = len(str(props))
        if total + node_chars > char_budget:
            break
        nodes.append(node)
        total += node_chars
        if len(nodes) >= 5:
            break

    if not nodes:
        return ""

    context = serialize_context(nodes)
    context += "\n\nOptimiza este codigo. Busca: bucles innecesarios, I/O bloqueante, "
    context += "copias de datos, complejidad algoritmica alta."
    return context


def _compress_audit(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Funciones target con foco en seguridad."""
    nodes = []
    seen = set()

    for c in top_capsules:
        if c.name in seen or c.type not in ("function", "class", "async_function"):
            continue
        seen.add(c.name)
        props = {
            "signature": c.signature,
            "file_path": c.file_path,
            "docstring": c.docstring or "",
            "parametros": c.properties.get("parametros", ""),
            "calls": ", ".join(c.calls[:8]),
        }
        nodes.append({
            "id": c.id, "name": c.name, "type": c.type,
            "properties": props,
        })
        if len(nodes) >= 10:
            break

    if not nodes:
        return ""

    context = serialize_context(nodes)
    context += "\n\nAudita este codigo por seguridad. Busca: SQL injection, XSS, "
    context += "path traversal, hardcoded secrets, input validation, auth bypass."
    return context


def _compress_onboard(all_capsules: list[Capsule]) -> str:
    """Mapa de alto nivel: estructura de directorios + entrypoints + módulos principales."""
    dirs = set()
    files_by_dir: dict[str, list[str]] = {}
    modules: list[Capsule] = []

    for c in all_capsules:
        parts = c.file_path.replace("\\", "/").split("/")
        dirname = "/".join(parts[:-1]) if len(parts) > 1 else "."
        for i in range(len(parts) - 1):
            dirs.add("/".join(parts[:i + 1]))
        files_by_dir.setdefault(dirname, []).append(parts[-1])
        if c.type in ("entrypoint", "file_header"):
            modules.append(c)

    lines = ["ESTRUCTURA DEL PROYECTO:"]
    for d in sorted(dirs):
        files = files_by_dir.get(d, [])
        if files:
            lines.append(f"  {d}/ ({len(files)} archivos)")

    if modules:
        lines.append("\nPUNTOS DE ENTRADA:")
        for m in modules[:10]:
            lines.append(f"  [{m.type}] {m.name} — {m.file_path}")

    lines.append(f"\nTotal: {len(all_capsules)} capsulas, {len(files_by_dir)} modulos")
    lines.append("Usa search_code y list_files para explorar en detalle.")

    return "\n".join(lines)
