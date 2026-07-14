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

import difflib
import re
from dataclasses import dataclass
from leo_code.core.parser import Capsule
from leo_code.core.context import serialize_context

_SIMILAR_NAME_THRESHOLD = 0.6
_AMBIGUITY_TYPES = {"function", "method", "class"}
_TRAILING_DIGITS = re.compile(r"\d+$")


def _has_similar_names(names: list[str]) -> bool:
    """Heuristica barata: nombres parecidos entre si (ej. _plan/_replan) son el
    escenario donde el LLM tiende a inventar un tercer nombre plausible que no
    existe (ej. _plan_step) en vez de verificar cual es el real. Excluye el caso
    comun de nombres enumerados (item0/item1/item2...) — distinguibles a simple
    vista por el sufijo numerico, no es la ambiguedad que nos preocupa."""
    uniq = [n for n in dict.fromkeys(names) if len(n) >= 4]
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            a, b = uniq[i], uniq[j]
            if _TRAILING_DIGITS.sub("", a) == _TRAILING_DIGITS.sub("", b):
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= _SIMILAR_NAME_THRESHOLD:
                return True
    return False


@dataclass
class CompressConfig:
    """Config para estrategia de compresión."""
    include_body: bool = False
    include_calls: bool = False
    include_imports: bool = False
    max_items: int = 10
    include_callees: bool = False
    include_callers: bool = False
    callees_depth: int = 1
    callers_limit: int = 5
    type_filter: set[str] | None = None
    footer_msg: str = ""
    body_chars: int = 2000  # cap por cuerpo cuando include_body


COMPRESS_STRATEGIES = {
    "code_edit": CompressConfig(
        max_items=5, include_calls=False, type_filter={"function", "class"},
        footer_msg="\n\nUsa read_file para ver el contenido completo antes de modificar."
    ),
    "refactor": CompressConfig(
        include_callees=True, include_callers=True, callers_limit=5,
        footer_msg="\n\nRefactoriza considerando callers y callees."
    ),
    "debug": CompressConfig(
        include_body=True, include_callees=True, include_callers=True,
        callers_limit=5, callees_depth=2,
        footer_msg="\n\nDepura la funcion target. Revisa callers y callees. Usa read_file si necesitas mas contexto."
    ),
    "test_gen": CompressConfig(
        include_calls=True, max_items=10,
        footer_msg="\n\nGenera tests para la funcion target. Usa los tests existentes como referencia de estilo."
    ),
    "review": CompressConfig(
        include_calls=True, max_items=10,
        footer_msg="\n\nRevisa este codigo. Busca bugs, problemas de estilo, seguridad, y mejoras."
    ),
    "audit": CompressConfig(
        include_calls=True, max_items=10,
        footer_msg="\n\nAudita este codigo por seguridad. Busca: SQL injection, XSS, path traversal, hardcoded secrets, input validation, auth bypass."
    ),
}


def compress(
    top_capsules: list[Capsule],
    all_capsules: list[Capsule],
    budget_tokens: int = 1500,
    task_type: str = "code_query",
    dir_filter: set[str] | None = None,
    query: str = "",
    self_sufficient: bool = False,
) -> str:
    """Compresión adaptativa según tipo de tarea.

    self_sufficient (vía MCP): el cliente es un agente genérico SIN nuestras
    tools de seguimiento — si el contexto no basta, relee archivos enteros y
    duplica el coste (medido en benchmark: hasta 15 relecturas/tarea). Incluye
    cuerpos completos y no manda a read_file."""

    if task_type == "no_code":
        doc_caps = [c for c in top_capsules if c.type == "document"]
        if doc_caps:
            return _compress_query(doc_caps, budget_tokens)
        return _compress_query(top_capsules, max(budget_tokens, 800))

    # Para code tasks: excluir docs de dominio del contexto
    top_capsules = [c for c in top_capsules if c.type != "document"]
    all_capsules  = [c for c in all_capsules  if c.type != "document"]

    # Framework-aware: priorizar cápsulas del framework mencionado en la query
    framework = _detect_framework_query(query)
    if framework:
        fw_caps = [c for c in all_capsules if c.properties.get("framework") == framework]
        top_capsules = _interleave_framework(top_capsules, fw_caps)

    result = ""

    if task_type == "code_gen":
        result = _compress_code_gen(all_capsules)
    elif task_type == "search":
        result = _compress_search(top_capsules, all_capsules, budget_tokens, dir_filter)
    elif task_type == "onboard":
        result = _compress_onboard(all_capsules)
    elif task_type == "design_review":
        result = _compress_design_review(top_capsules, all_capsules)
    elif task_type == "optimize":
        result = _compress_optimize(top_capsules, all_capsules)
    elif task_type in COMPRESS_STRATEGIES:
        # Usar estrategia configurada
        config = COMPRESS_STRATEGIES[task_type]
        if self_sufficient:
            from dataclasses import replace
            # body_chars 2500 (no 6000): en c5b la respuesta gorda cebaba mas
            # exploracion en vez de sustituirla, y viaja en cada turno.
            config = replace(config, include_body=True, body_chars=2500,
                             footer_msg="\n\nEl codigo relevante ya esta incluido arriba: trabaja con el, no releas archivos.")
        result = _build_nodes_from_config(top_capsules, all_capsules, config, task_type)
    else:
        # Default: code_query
        result = _compress_query(top_capsules, budget_tokens)

    # Inyectar paths explícitos al inicio del contexto
    files = list(dict.fromkeys(c.file_path for c in top_capsules[:8] if c.file_path))
    if files and result:
        result = f"ARCHIVOS: {', '.join(files)}\n\n{result}"

    return result


def _build_nodes_from_config(
    top_capsules: list[Capsule],
    all_capsules: list[Capsule],
    config: CompressConfig,
    task_type: str,
) -> str:
    """Construye nodos según config. Consolida lógica duplicada."""
    target = top_capsules[0] if top_capsules else None
    if not target and task_type != "test_gen":
        return ""

    nodes = []
    all_by_name = {c.name: c for c in all_capsules}
    seen = set()

    # Target o primeros capsules
    for i, c in enumerate(top_capsules[:config.max_items]):
        if c.name in seen:
            continue
        if config.type_filter and c.type not in config.type_filter:
            continue
        seen.add(c.name)

        props = {
            "signature": c.signature,
            "file_path": c.file_path,
            "docstring": c.docstring or "",
        }

        if config.include_body and c.content:
            body = c.content
            if len(body) > config.body_chars:
                body = body[:config.body_chars] + "\n# ... [truncado]"
            props["content"] = body

        if config.include_calls and c.calls:
            props["calls"] = ", ".join(c.calls[:8])

        if config.include_imports and c.imports:
            props["imports"] = ", ".join(c.imports[:8])

        if "parametros" in c.properties:
            props["parametros"] = c.properties["parametros"]
        if "tipo_retorno" in c.properties:
            props["tipo_retorno"] = c.properties["tipo_retorno"]
        if "lineas" in c.properties:
            props["lineas"] = c.properties["lineas"]

        nodes.append({"id": c.id, "name": c.name, "type": c.type, "properties": props})

        if i == 0 and config.include_callees:
            # Callees del target
            for call in c.calls[:8]:
                if call in all_by_name and call not in seen:
                    callee = all_by_name[call]
                    seen.add(callee.name)
                    nodes.append({
                        "id": callee.id, "name": callee.name, "type": callee.type,
                        "properties": {
                            "signature": callee.signature,
                            "file_path": callee.file_path,
                            "docstring": callee.docstring or "",
                        },
                    })

        if i == 0 and config.include_callers:
            # Callers del target
            callers = [c2 for c2 in all_capsules if target.name in c2.calls]
            for caller in callers[:config.callers_limit]:
                if caller.name not in seen:
                    seen.add(caller.name)
                    nodes.append({
                        "id": caller.id, "name": caller.name, "type": caller.type,
                        "properties": {
                            "signature": caller.signature,
                            "file_path": caller.file_path,
                            "docstring": caller.docstring or "",
                            "calls": ", ".join(caller.calls[:5]) if caller.calls else "",
                        },
                    })

    # Tests existentes (solo test_gen)
    if task_type == "test_gen":
        test_caps = [c for c in all_capsules if "test" in c.name.lower() and c.type in ("function", "class")]
        if test_caps:
            nodes.append({
                "id": "__tests__", "name": "__tests__", "type": "section",
                "properties": {"descripcion": f"{len(test_caps)} tests existentes en el repo"},
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

    shown = [n for n in nodes if n.get("type") in _AMBIGUITY_TYPES]
    if len(shown) >= 2 and _has_similar_names([n["name"] for n in shown]):
        listing = "\n".join(f"- {n['name']} — {n['properties'].get('file_path', '?')}" for n in shown)
        nodes.append({
            "id": "__symbols_found__", "name": "__symbols_found__", "type": "section",
            "properties": {"descripcion":
                f"SIMBOLOS REALES ENCONTRADOS (unicos validos, no hay otros):\n{listing}\n"
                "No inventes ni asumas otro nombre parecido. Si necesitas confirmar si "
                "existe alguno distinto, usa find_symbol o search_code ANTES de afirmar "
                "algo sobre el."},
        })
        if target and not config.include_body and target.content:
            target_node = next((n for n in nodes if n["id"] == target.id), None)
            if target_node and "content" not in target_node["properties"]:
                body = target.content[:1200]
                if len(target.content) > 1200:
                    body += "\n# ... [truncado]"
                target_node["properties"]["content"] = body

    context = serialize_context(nodes)
    if config.footer_msg:
        context += config.footer_msg
    return context


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

        # Primera cápsula relevante: incluir cuerpo completo si cabe.
        # "method" incluido: es el tipo mayoritario del repo; sin él, toda query
        # sobre un método devolvía solo firma (cero precisión sobre su lógica).
        if i == 0 and c.content and c.type in ("function", "method", "class", "document", "file_header"):
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
            # No cabe entero: truncar la CABEZA (firma + lógica inicial) en vez de
            # tirar el cuerpo entero. Cero cuerpo = cero precisión sobre la lógica.
            room = char_budget - total_chars - 80  # margen para fences + marcador
            if room > 400 and c.type not in ("document", "file_header"):
                head = c.content[:room]
                body_text = f"[{c.name}|{c.type}] {c.file_path}\n```\n{head}\n# ... [truncado]\n```"
                parts.append(body_text)
                total_chars += len(body_text)
                continue

        # Saltar nodos que son solo imports ("from X import Y" / "import X"): cero
        # lógica, ya cubiertos por el campo Imports del header → puro ruido de tokens.
        sig = (c.signature or "").lstrip()
        if i > 0 and (sig.startswith("from ") or sig.startswith("import ")):
            continue

        # Resto: firma + docstring + relaciones. Omitir file_path cuando coincide
        # con el archivo líder (ya está en el header ARCHIVOS) → menos ruido; los
        # vecinos de OTROS archivos sí lo conservan para no perder atribución.
        lead_file = top_capsules[0].file_path if top_capsules else None
        props = {"signature": c.signature, "docstring": c.docstring or ""}
        if c.file_path and c.file_path != lead_file:
            props["file_path"] = c.file_path
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


def _compress_design_review(top_capsules: list[Capsule], all_capsules: list[Capsule]) -> str:
    """Imágenes + HTML/CSS estructural + instrucciones de diseño."""
    nodes = []

    # Imágenes primero
    images = [c for c in all_capsules if c.type == "image"]
    for img in images[:3]:
        nodes.append({
            "id": img.id, "name": img.name, "type": "image",
            "properties": {
                "file_path": img.file_path,
                "mime": img.properties.get("mime", ""),
                "size_bytes": img.properties.get("size_bytes", 0),
            },
        })

    # HTML/CSS del repo
    html_caps = [c for c in all_capsules if c.language in ("html", "css")]
    for c in html_caps[:5]:
        props = {"file_path": c.file_path}
        for key in ("tags", "css_classes", "meta_tags", "headings", "selectors",
                     "colors", "fonts", "media_queries"):
            if key in c.properties:
                props[key] = c.properties[key]
        nodes.append({"id": c.id, "name": c.name, "type": c.type, "properties": props})

    # Top code capsules por si hay componentes React/Vue/Svelte
    code_caps = [c for c in top_capsules if c.language in ("javascript", "typescript")][:3]
    for c in code_caps:
        nodes.append({
            "id": c.id, "name": c.name, "type": c.type,
            "properties": {
                "signature": c.signature,
                "file_path": c.file_path,
                "docstring": c.docstring or "",
            },
        })

    context = serialize_context(nodes) if nodes else ""
    context += "\n\nAnaliza el diseño, copy, colores, accesibilidad, jerarquía visual y UX."
    if images:
        context += f" Hay {len(images)} imagen(es) para analizar."
        context += " Revisa: paleta de colores, tipografía, espaciado, contraste, CTA, copy, estructura visual."
    if html_caps:
        context += f" {len(html_caps)} archivo(s) HTML/CSS disponibles."
    return context


_FRAMEWORK_QUERIES = {
    "fastapi": ["fastapi", "fast api"],
    "flask": ["flask"],
    "django": ["django"],
    "react": ["react", "reactjs"],
    "express": ["express", "expressjs"],
    "next": ["next.js", "nextjs", "next js"],
    "nestjs": ["nestjs", "nest js", "nest.js"],
    "spring": ["spring", "spring boot", "springboot"],
    "pydantic": ["pydantic"],
    "sqlalchemy": ["sqlalchemy", "sql alchemy"],
    "graphql": ["graphql", "graph ql"],
    "laravel": ["laravel"],
    "dotnet": [".net", "dotnet", "asp.net", "asp net"],
    "vue": ["vue", "vuejs", "vue.js"],
    "celery": ["celery"],
    "aiohttp": ["aiohttp", "aio http"],
    "sqlmodel": ["sqlmodel", "sql model"],
    "strawberry": ["strawberry graphql"],
    "angular": ["angular", "angularjs"],
    "svelte": ["svelte", "sveltekit"],
    "nuxt": ["nuxt", "nuxt.js"],
    "remix": ["remix"],
    "rails": ["rails", "ruby on rails"],
    "sinatra": ["sinatra"],
    "gin": ["gin", "gin gonic", "gin-go"],
    "echo": ["echo go", "echo framework"],
    "fiber": ["fiber", "fiber go"],
    "hibernate": ["hibernate"],
    "jakarta": ["jakarta", "jakarta ee", "jax-rs"],
    "quarkus": ["quarkus"],
    "actix": ["actix", "actix web", "actix-web"],
    "axum": ["axum"],
    "symfony": ["symfony"],
    "entity_framework": ["entity framework", "ef core"],
    "phoenix": ["phoenix", "elixir phoenix"],
}


def _detect_framework_query(query: str) -> str:
    q = query.lower()
    for fw, signals in _FRAMEWORK_QUERIES.items():
        if any(s in q for s in signals):
            return fw
    return ""


def _interleave_framework(top: list, fw_caps: list) -> list:
    fw_ids = {c.id for c in fw_caps}
    fw_matches = [c for c in top if c.id in fw_ids]
    others = [c for c in top if c.id not in fw_ids]
    return (fw_matches[:8] + others[:15])[:30]
