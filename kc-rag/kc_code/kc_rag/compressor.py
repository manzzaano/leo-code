"""Compressor adaptativo: construye el prompt según el tipo de tarea.

Estrategias:
- code_gen: solo estructura de directorios y archivos del repo
- code_edit: función target + sus dependencias directas (sin cuerpos completos)
- code_query: top 5 con docstrings, sin cuerpos
- refactor: target + callers + callees (BFS depth 1)
- search: mini-mapa ligero
- no_code: contexto vacío
"""

from kc_core.parser import Capsule
from kc_core.context import serialize_context


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
