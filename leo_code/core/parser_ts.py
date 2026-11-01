"""parser_ts — extractor TS/JS por AST real (tree-sitter), no regex.

El parser genérico (parser_generic) deriva las llamadas de TS/JS con una regex
`(\\w+)\\s*\\(` capada a 10 y con denylist: ni SOUND (captura `foo(` de cualquier
palabra) ni COMPLETE (cap 10, límites de bloque por regex). Contra un oráculo del
compilador TS daba precisión 74% / recall 60%.

Aquí los límites de cada símbolo (function/method/class) y sus llamadas vienen del
árbol de sintaxis de tree-sitter, con la MISMA regla de callee que el oráculo:
CallExpression cuyo callee es `identifier` (foo()) o `member_expression` (obj.foo())
→ nombre base, igual en `new Foo()` y en `<Foo/>`. Sin cap, sin truncado, sin denylist.
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
    # envolviendo al callee. tsc resuelve a la llamada interna; desenvolvemos el unario. Igual con `await fn<T>(x)`.
    while fn is not None and fn.type in ("unary_expression", "await_expression"):
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


def _new_name(node) -> str | None:
    """`new Foo()` / `new ns.Foo()` → Foo. Sin esto ninguna clase TS tenía dependientes
    (medido: 2428/2451 en nest): en TS se instancia con `new`, no con una llamada."""
    k = node.child_by_field_name("constructor")
    if k is None:
        return None
    if k.type == "identifier":
        return k.text.decode("utf-8", "replace")
    if k.type == "member_expression":
        prop = k.child_by_field_name("property")
        return prop.text.decode("utf-8", "replace") if prop is not None else None
    return None


def _jsx_name(node) -> str | None:
    """`<Card/>` / `<ui.Modal>` → componente. En minúscula es etiqueta HTML (`<div>`,
    `<motion.div>`), no un símbolo. Medido: 288 componentes de excalidraw sin callers."""
    k = node.child_by_field_name("name")
    if k is None or k.type not in ("identifier", "member_expression", "nested_identifier"):
        return None
    nm = k.text.decode("utf-8", "replace").rsplit(".", 1)[-1]
    return nm if nm[:1].isupper() else None


_CALL_NODES = {"call_expression": _callee_name, "new_expression": _new_name,
               "jsx_opening_element": _jsx_name, "jsx_self_closing_element": _jsx_name}


def _new_name(node) -> str | None:
    """`new Foo()` / `new ns.Foo()` → Foo. Sin esto ninguna clase TS tenía dependientes
    (medido: 2428/2451 en nest): en TS se instancia con `new`, no con una llamada."""
    k = node.child_by_field_name("constructor")
    if k is None:
        return None
    if k.type == "identifier":
        return k.text.decode("utf-8", "replace")
    if k.type == "member_expression":
        prop = k.child_by_field_name("property")
        return prop.text.decode("utf-8", "replace") if prop is not None else None
    return None


def _jsx_name(node) -> str | None:
    """`<Card/>` / `<ui.Modal>` → componente. En minúscula es etiqueta HTML (`<div>`,
    `<motion.div>`), no un símbolo. Medido: 288 componentes de excalidraw sin callers."""
    k = node.child_by_field_name("name")
    if k is None or k.type not in ("identifier", "member_expression", "nested_identifier"):
        return None
    nm = k.text.decode("utf-8", "replace").rsplit(".", 1)[-1]
    return nm if nm[:1].isupper() else None


_CALL_NODES = {"call_expression": _callee_name, "new_expression": _new_name,
               "jsx_opening_element": _jsx_name, "jsx_self_closing_element": _jsx_name}


def _calls_in(node) -> list[str]:
    """Todos los nombres llamados dentro del subárbol (incluye anidados, como el oráculo)."""
    out: list[str] = []
    seen: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        namer = _CALL_NODES.get(n.type)
        if namer:
            nm = namer(n)
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

# TS/JS idiomático declara funciones como variables u objetos de funciones, no con
# `function`: `const Page = () => …`, `const load = useCallback(() => …)`,
# `export const api = { jobs: () => get("/api/jobs") }`. Sin esto, en un frontend React
# real casi nada era un símbolo (medido en NEXUS: el trace frontend→backend no cruzaba).
# MISMA regla en el oráculo tsc (benchmark/ts_oracle.js): VariableDeclaration /
# PropertyAssignment cuyo initializer es arrow/function, o una llamada que envuelve una
# (patrón useCallback/useMemo/memo).
_FN_VALUES = {"arrow_function", "function_expression"}
# Envoltorios que DEVUELVEN la función (siguen siendo una función con nombre). Lista
# blanca a propósito: `const idx = xs.findIndex(t => …)` o `useMemo(() => …)` devuelven
# un VALOR, no una función, y colarlos inventaba símbolos (visto en NEXUS: `idx`, `widths`).
_FN_WRAPPERS = {"useCallback", "memo", "forwardRef", "observer", "useEventCallback", "useMemoizedFn"}


def _fn_value(node):
    """El nodo-función de un initializer, si lo hay (directo o vía envoltorio conocido)."""
    if node is None:
        return None
    if node.type in _FN_VALUES:
        return node
    if node.type == "call_expression":
        fn = node.child_by_field_name("function")
        callee = fn.text.decode("utf-8", "replace").split(".")[-1] if fn is not None else ""
        if callee not in _FN_WRAPPERS:
            return None
        args = node.child_by_field_name("arguments")
        for child in (args.children if args is not None else []):
            if child.type in _FN_VALUES:
                return child
    return None


def extract_from_tree_sitter(content: str, file_path: str, language: str) -> list[Capsule]:
    grammar = "javascript" if language == "javascript" else (
        "tsx" if str(file_path).endswith(".tsx") else "typescript")
    tree = _parser(grammar).parse(content.encode("utf-8"))
    lines = content.split("\n")
    caps: list[Capsule] = []

    def emit(name: str, kind: str, node) -> None:
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1
        ctype = kind
        body = "\n".join(lines[start - 1:end])
        caps.append(Capsule(
            id=f"{file_path}:{start}:{name}",
            type=ctype, name=name, file_path=file_path,
            start_line=start, end_line=end,
            language=language, signature=f"{kind} {name}",
            content=body[:3000], calls=_calls_in(node),
            properties={"lineas": end - start + 1},
        ))

    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type == "variable_declarator":
            # `const f = () => …` / `const f = function(){}` / `const f = useCallback(() => …)`
            name_node = n.child_by_field_name("name")
            if (name_node is not None and name_node.type == "identifier"
                    and _fn_value(n.child_by_field_name("value")) is not None):
                emit(name_node.text.decode("utf-8", "replace"), "function", n)
        elif n.type == "pair":
            # objeto de funciones: `export const api = { jobs: () => get("/api/jobs") }`
            key = n.child_by_field_name("key")
            if (key is not None and key.type in ("property_identifier", "identifier")
                    and _fn_value(n.child_by_field_name("value")) is not None):
                emit(key.text.decode("utf-8", "replace"), "function", n)
        elif n.type in ("public_field_definition", "field_definition"):
            # `class C { onClick = () => … }`: en TS el nombre es `name`, en JS `property`
            key = n.child_by_field_name("name") or n.child_by_field_name("property")
            if (key is not None and key.type in ("property_identifier", "private_property_identifier")
                    and _fn_value(n.child_by_field_name("value")) is not None):
                emit(key.text.decode("utf-8", "replace"), "method", n)
        elif n.type == "assignment_expression" and _fn_value(n.child_by_field_name("right")) is not None:
            # `a.b = function(){}`, `Foo.prototype.m = () => …`, `exports.e = …`
            left = n.child_by_field_name("left")
            prop = left.child_by_field_name("property") if left.type == "member_expression" else None
            nm = (prop if prop is not None else left).text.decode("utf-8", "replace")
            if (left.type == "identifier" or prop is not None) and nm != "exports":
                emit(nm, "function", n)
        kind = _DEF_NODES.get(n.type)
        if kind:
            name_node = n.child_by_field_name("name")
            if name_node is not None:
                emit(name_node.text.decode("utf-8", "replace"), kind, n)
        stack.extend(n.children)
    return caps
