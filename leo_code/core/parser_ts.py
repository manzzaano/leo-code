"""parser_ts — extractor TS/JS por AST real (tree-sitter), no regex.

El parser genérico (parser_generic) deriva las llamadas de TS/JS con una regex
`(\\w+)\\s*\\(` capada a 10 y con denylist: ni SOUND (captura `foo(` de cualquier
palabra) ni COMPLETE (cap 10, límites de bloque por regex). Contra un oráculo del
compilador TS daba precisión 74% / recall 60%.

Aquí los límites de cada símbolo (function/method/class) y sus llamadas vienen del
árbol de sintaxis de tree-sitter, con la MISMA regla de callee que el oráculo:
CallExpression cuyo callee es `identifier` (foo()) o `member_expression` (obj.foo())
→ nombre base. Sin cap, sin truncado, sin denylist.
"""

from __future__ import annotations

from pathlib import Path

from leo_code.core.parser import Capsule

_PARSERS: dict[str, object] = {}


def _parser(grammar: str):
    """Parser tree-sitter cacheado para 'typescript' | 'tsx' | 'javascript'."""
    if grammar in _PARSERS:
        return _PARSERS[grammar]
    import tree_sitter as TS
    if grammar == "javascript":
        import tree_sitter_javascript as g
        lang = TS.Language(g.language())
    elif grammar == "tsx":
        import tree_sitter_typescript as g
        lang = TS.Language(g.language_tsx())
    else:
        import tree_sitter_typescript as g
        lang = TS.Language(g.language_typescript())
    p = TS.Parser(lang)
    _PARSERS[grammar] = p
    return p


def _callee_name(call_node) -> str | None:
    """Nombre base del callee, espejo del oráculo tsc: identifier o member.property."""
    # Tagged template (`tag`...``): tree-sitter lo marca call_expression, pero tsc lo trata
    # como TaggedTemplateExpression —NO una llamada—. Sus args son un template_string.
    args = call_node.child_by_field_name("arguments")
    if args is not None and args.type == "template_string":
        return None
    fn = call_node.child_by_field_name("function")
    if fn is None:
        return None
    # Quirk de tree-sitter: en `!!fn<T>(x)` el `function` queda como unary_expression
    # envolviendo al callee. tsc resuelve a la llamada interna; desenvolvemos el unario.
    while fn is not None and fn.type == "unary_expression":
        fn = fn.children[-1] if fn.children else None
    if fn is None:
        return None
    if fn.type == "identifier":
        return fn.text.decode("utf-8", "replace")
    if fn.type == "member_expression":
        prop = fn.child_by_field_name("property")
        if prop is not None:
            return prop.text.decode("utf-8", "replace")
    return None


def _calls_in(node) -> list[str]:
    """Todos los nombres llamados dentro del subárbol (incluye anidados, como el oráculo)."""
    out: list[str] = []
    seen: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            nm = _callee_name(n)
            if nm and nm not in seen:
                seen.add(nm); out.append(nm)
        stack.extend(n.children)
    return out


# nodos-definición que el oráculo tsc también reconoce (FunctionDeclaration /
# MethodDeclaration / ClassDeclaration), con sus variantes de tree-sitter.
_DEF_NODES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
}


def extract_from_tree_sitter(content: str, file_path: str, language: str) -> list[Capsule]:
    grammar = "javascript" if language == "javascript" else (
        "tsx" if str(file_path).endswith(".tsx") else "typescript")
    tree = _parser(grammar).parse(content.encode("utf-8"))
    lines = content.split("\n")
    caps: list[Capsule] = []

    def name_of(node):
        nm = node.child_by_field_name("name")
        return nm.text.decode("utf-8", "replace") if nm is not None else None

    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        kind = _DEF_NODES.get(n.type)
        if kind:
            name = name_of(n)
            if name:
                start = n.start_point[0] + 1
                end = n.end_point[0] + 1
                ctype = "class" if kind == "class" else ("method" if kind == "method" else "function")
                body = "\n".join(lines[start - 1:end])
                caps.append(Capsule(
                    id=f"{file_path}:{start}:{name}",
                    type=ctype, name=name, file_path=file_path,
                    start_line=start, end_line=end,
                    language=language, signature=f"{kind} {name}",
                    content=body[:3000], calls=_calls_in(n),
                    properties={"lineas": end - start + 1},
                ))
        stack.extend(n.children)
    return caps
