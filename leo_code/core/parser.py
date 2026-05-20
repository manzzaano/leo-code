"""Parser de código fuente a cápsulas (funciones, clases, módulos).

Soporta Python vía ast.parse() y tree-sitter para multi-lenguaje.
"""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Capsule:
    id: str
    type: str  # function, class, module, variable, constant
    name: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    signature: str
    content: str
    docstring: Optional[str] = None
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


def _make_id(file_path: str, start_line: int, signature: str) -> str:
    raw = f"{file_path}::{start_line}::{signature}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def extract_from_python(content: str, file_path: str) -> list[Capsule]:
    """Extrae cápsulas del AST de un archivo Python. 0 dependencias externas."""
    capsules = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return capsules

    module_name = Path(file_path).name

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                capsules.append(Capsule(
                    id=_make_id(file_path, node.lineno, f"import {alias.name}"),
                    type="module", name=alias.name, file_path=file_path,
                    start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                    language="python", signature=f"import {alias.name}",
                    content=ast.unparse(node),
                    imports=[alias.name],
                ))

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                full = f"{mod}.{alias.name}" if mod else alias.name
                capsules.append(Capsule(
                    id=_make_id(file_path, node.lineno, f"from {mod} import {alias.name}"),
                    type="function" if alias.name[0].islower() else "class",
                    name=full, file_path=file_path,
                    start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                    language="python", signature=f"from {mod} import {alias.name}",
                    content=ast.unparse(node),
                    imports=[mod] if mod else [],
                ))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_async = isinstance(node, ast.AsyncFunctionDef)

            def _param_str(arg, default=None) -> str:
                p = f"{arg.arg}: {ast.unparse(arg.annotation)}" if arg.annotation else arg.arg
                return f"{p} = {ast.unparse(default)}" if default is not None else p

            all_args = node.args.args
            defaults = node.args.defaults
            pad = len(all_args) - len(defaults)
            params = [_param_str(a, defaults[i - pad] if i >= pad else None) for i, a in enumerate(all_args)]
            returns = ast.unparse(node.returns) if node.returns else "None"
            doc = ast.get_docstring(node)
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            prefix = "async def" if is_async else "def"
            sig = f"{prefix} {node.name}({', '.join(params)}) -> {returns}"

            calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    calls.append(child.func.id)

            if not doc and lines <= 15:
                doc = (ast.get_source_segment(content, node) or "")[:300]

            # Decorators
            decorators = [
                ast.unparse(d) for d in node.decorator_list
            ] if node.decorator_list else []

            # Capsule type differentiation
            if node.name.startswith("test_"):
                ftype = "test"
            elif is_async:
                ftype = "async_function"
            elif any("pytest.fixture" in d or "fixture" == d.split("(")[0].strip("@") for d in decorators):
                ftype = "test"
            else:
                ftype = "function"

            props = {
                "parametros": ", ".join(params),
                "tipo_retorno": returns,
                "lineas": lines,
                "module": module_name,
            }
            if decorators:
                props["decorators"] = ", ".join(decorators)

            capsules.append(Capsule(
                id=_make_id(file_path, node.lineno, sig),
                type=ftype, name=node.name, file_path=file_path,
                start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                language="python", signature=sig,
                content=ast.get_source_segment(content, node) or ast.unparse(node),
                docstring=doc, calls=calls,
                properties=props,
            ))

        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            methods = [n.name for n in ast.iter_child_nodes(node)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            doc = ast.get_docstring(node)
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"

            calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    calls.append(child.func.id)

            decorators = [
                ast.unparse(d) for d in node.decorator_list
            ] if node.decorator_list else []

            is_dataclass = any(
                d.split("(")[0].strip("@") == "dataclass"
                for d in decorators
            )
            is_exception = any(
                b.split("(")[0].split("[")[0].split(".")[-1] in ("Exception", "BaseException", "ValueError", "TypeError", "KeyError", "RuntimeError", "OSError", "IOError", "HTTPException")
                for b in bases
            )

            if is_dataclass:
                ctype = "dataclass"
            elif is_exception:
                ctype = "exception"
            else:
                ctype = "class"

            props = {
                "metodos": ", ".join(methods),
                "hereda_de": ", ".join(bases),
                "lineas": lines,
                "module": module_name,
            }
            if decorators:
                props["decorators"] = ", ".join(decorators)

            capsules.append(Capsule(
                id=_make_id(file_path, node.lineno, sig),
                type=ctype, name=node.name, file_path=file_path,
                start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                language="python", signature=sig,
                content=ast.get_source_segment(content, node) or ast.unparse(node),
                docstring=doc, calls=calls,
                properties=props,
            ))

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    ctype = "constant" if t.id.isupper() else "variable"
                    raw = ast.get_source_segment(content, node) or ast.unparse(node)
                    sig = raw if len(raw) <= 120 else f"{t.id} = ..."
                    capsules.append(Capsule(
                        id=_make_id(file_path, node.lineno, f"{ctype} {t.id}"),
                        type=ctype, name=t.id, file_path=file_path,
                        start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                        language="python", signature=sig,
                        content=raw,
                        properties={"module": module_name},
                    ))

        elif isinstance(node, ast.If):
            # __name__ == "__main__" entrypoint
            test_str = ast.unparse(node.test) if node.test else ""
            if "__name__" in test_str and "__main__" in test_str:
                entry_content = ast.get_source_segment(content, node) or ast.unparse(node)
                capsules.append(Capsule(
                    id=_make_id(file_path, node.lineno, "entrypoint"),
                    type="entrypoint", name=f"{module_name}.__main__", file_path=file_path,
                    start_line=node.lineno, end_line=node.end_lineno or node.lineno,
                    language="python", signature="if __name__ == '__main__'",
                    content=entry_content[:2000],
                    properties={
                        "lineas": (node.end_lineno or node.lineno) - node.lineno + 1,
                        "module": module_name,
                    },
                ))

    header = _extract_file_header(content, file_path)
    if header is not None:
        capsules.append(header)

    return capsules


def _extract_file_header(content: str, file_path: str) -> Optional[Capsule]:
    """Cápsula tipo file_header: bloque de imports + constantes top-level hasta la primera función/clase."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    lines = content.splitlines()
    module_name = Path(file_path).stem
    module_docstring = ast.get_docstring(tree) or None

    header_end = 0
    imports_list: list[str] = []
    constants: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            break
        line_end = getattr(node, "end_lineno", node.lineno)
        header_end = max(header_end, line_end)
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports_list.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = ", ".join(a.name for a in node.names)
            imports_list.append(f"{node.module}: {names}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    constants.append(t.id)

    if header_end == 0:
        return None

    header_content = "\n".join(lines[:header_end])
    return Capsule(
        id=_make_id(file_path, 1, f"file_header:{module_name}"),
        type="file_header",
        name=f"{module_name}.__header__",
        file_path=file_path,
        start_line=1,
        end_line=header_end,
        language="python",
        signature=f"[imports] {module_name}",
        content=header_content,
        docstring=module_docstring,
        imports=imports_list,
        properties={
            "module": module_name,
            "constants": ", ".join(constants),
            "import_lines": header_end,
        },
    )


def extract_from_txt(content: str, file_path: str) -> list[Capsule]:
    """Extrae una cápsula de tipo document de un archivo .txt."""
    name = Path(file_path).stem
    first_line = content.strip().split("\n")[0].strip()
    return [Capsule(
        id=_make_id(file_path, 1, f"doc:{name}"),
        type="document",
        name=name,
        file_path=file_path,
        start_line=1,
        end_line=content.count("\n") + 1,
        language="text",
        signature=f"[doc] {name}",
        content=content.strip(),
        docstring=content.strip()[:300],
        properties={"chars": len(content)},
    )]


EXT_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".html": "html", ".htm": "html",
    ".css": "css",
    ".txt": "text", ".md": "text", ".rst": "text", ".cfg": "text", ".ini": "text",
    ".toml": "text", ".yaml": "text", ".yml": "text", ".json": "text",
    ".xml": "text", ".sql": "text",
    ".sh": "text", ".bash": "text", ".ps1": "text", ".bat": "text",
    ".dockerfile": "text", ".makefile": "text", ".cmake": "text",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".bmp": "image", ".ico": "image",
}

LANGUAGES = sorted(set(EXT_LANG.values()))


def detect_language(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    name = Path(file_path).name.lower()
    if name in ("dockerfile", "makefile", "gemfile", "rakefile", "cmakelists.txt"):
        return "text"
    return EXT_LANG.get(suffix, "text")


def extract_from_file(path: str, language: str = "python") -> list[Capsule]:
    """Extrae cápsulas de un archivo. Selecciona parser según lenguaje."""
    if language == "image":
        return extract_image_capsule(path)
    content = Path(path).read_text(encoding="utf-8")
    if language == "python":
        return extract_from_python(content, path)
    if language == "text":
        return extract_from_txt(content, path)
    if language in ("html", "css"):
        try:
            from leo_code.core.parser_generic import extract_html_css
            return extract_html_css(content, path, language)
        except ImportError:
            return extract_from_txt(content, path)
    try:
        from leo_code.core.parser_generic import extract_generic
        return extract_generic(content, path, language)
    except ImportError:
        pass
    try:
        return extract_from_tree_sitter(content, path, language)
    except (ImportError, SyntaxError, ValueError):
        return []


def extract_image_capsule(path: str) -> list[Capsule]:
    """Cápsula de tipo image con base64 para modelos de visión."""
    import base64
    name = Path(path).stem
    content = Path(path).read_bytes()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
                ".bmp": "image/bmp", ".ico": "image/x-icon"}
    suffix = Path(path).suffix.lower()
    mime = mime_map.get(suffix, "image/png")
    b64 = base64.b64encode(content).decode("ascii")
    return [Capsule(
        id=_make_id(path, 1, f"image:{name}"),
        type="image",
        name=name,
        file_path=path,
        start_line=1, end_line=1,
        language="image",
        signature=f"[image] {name} ({len(content)} bytes)",
        content=f"data:{mime};base64,{b64}",
        properties={"mime": mime, "size_bytes": len(content), "width": 0, "height": 0},
    )]

    tree = parser.parse(content.encode())
    root = tree.root_node
    capsules = []
    module_name = Path(file_path).name

    def _range(node) -> tuple[int, int]:
        return node.start_point[0] + 1, node.end_point[0] + 1

    def _text(node) -> str:
        return content[node.start_byte:node.end_byte]

    def _find_calls(node) -> list[str]:
        calls = []
        for child in node.children:
            if child.type == "call":
                func = child.child_by_field_name("function")
                if func and func.type == "identifier":
                    calls.append(_text(func))
            calls.extend(_find_calls(child))
        return calls

    def _find_imports(node) -> list[str]:
        imports = []
        if node.type in ("import_statement", "import_from_statement"):
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    imports.append(_text(child).split(" as ")[0])
                elif child.type == "import_prefix":
                    pass
            if node.type == "import_from_statement":
                mod = node.child_by_field_name("module_name")
                if mod:
                    imports.append(_text(mod))
        for child in node.children:
            imports.extend(_find_imports(child))
        return imports

    for node in root.children:
        if not node.is_named:
            continue

        start, end = _range(node)

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            return_node = node.child_by_field_name("return_type")
            body = node.child_by_field_name("body")
            name = _text(name_node) if name_node else "unknown"
            params = _text(params_node) if params_node else "()"
            ret_type = _text(return_node) if return_node else "None"
            sig = f"def {name}{params}"
            if return_node:
                sig += f" -> {ret_type}"
            doc = None
            if body:
                for child in body.children:
                    if child.type == "expression_statement":
                        expr = child.children[0] if child.children else None
                        if expr and expr.type == "string":
                            doc = _text(expr).strip("\"'").split("\n")[0].strip()
            calls = _find_calls(node) if body else []
            capsules.append(Capsule(
                id=_make_id(file_path, start, sig),
                type="function", name=name, file_path=file_path,
                start_line=start, end_line=end,
                language=language, signature=sig,
                content=_text(node), docstring=doc, calls=calls,
                properties={
                    "parametros": params.strip("()"),
                    "tipo_retorno": ret_type,
                    "lineas": end - start + 1,
                    "module": module_name,
                },
            ))

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            name = _text(name_node) if name_node else "unknown"
            sig = f"class {name}"
            doc = None
            methods = []
            calls = []
            if body:
                for child in body.children:
                    if child.type == "function_definition":
                        mname = _text(child.child_by_field_name("name"))
                        methods.append(mname)
                for child in body.children:
                    if child.type == "expression_statement":
                        expr = child.children[0] if child.children else None
                        if expr and expr.type == "string" and not doc:
                            doc = _text(expr).strip("\"'").split("\n")[0].strip()
                calls = _find_calls(body)
            capsules.append(Capsule(
                id=_make_id(file_path, start, sig),
                type="class", name=name, file_path=file_path,
                start_line=start, end_line=end,
                language=language, signature=sig,
                content=_text(node), docstring=doc, calls=calls,
                properties={
                    "metodos": ", ".join(methods),
                    "lineas": end - start + 1,
                    "module": module_name,
                },
            ))

        elif node.type in ("import_statement", "import_from_statement"):
            import_names = _find_imports(node)
            for imp_name in import_names:
                capsules.append(Capsule(
                    id=_make_id(file_path, start, f"import {imp_name}"),
                    type="module", name=imp_name, file_path=file_path,
                    start_line=start, end_line=end,
                    language=language, signature=f"import {imp_name}",
                    content=_text(node), imports=[imp_name],
                ))

        elif node.type == "expression_statement":
            for child in node.children:
                if child.type == "assignment":
                    lhs = child.child_by_field_name("left")
                    if lhs and lhs.type == "identifier":
                        name = _text(lhs)
                        rct = _text(child.child_by_field_name("right")) if child.child_by_field_name("right") else "..."
                        ctype = "constant" if name.isupper() else "variable"
                        capsules.append(Capsule(
                            id=_make_id(file_path, start, f"{ctype} {name}"),
                            type=ctype, name=name, file_path=file_path,
                            start_line=start, end_line=end,
                            language=language, signature=f"{name} = {rct[:30]}",
                            content=_text(node).split("\n")[0],
                            properties={"module": module_name},
                        ))

    return capsules


def build_call_graph(capsules: list[Capsule]) -> None:
    """Rellena called_by en todas las cápsulas a partir de calls."""
    name_to_id = {c.name: c.id for c in capsules}
    id_to_capsule = {c.id: c for c in capsules}
    for c in capsules:
        for call_name in c.calls:
            if call_name in name_to_id:
                target = id_to_capsule.get(name_to_id[call_name])
                if target and c.id not in target.called_by:
                    target.called_by.append(c.id)
