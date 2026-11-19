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

import re
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


_FN_LIKE = {"function_declaration", "generator_function_declaration", "function_expression",
            "generator_function", "arrow_function", "method_definition"}
_FIELDS = {"public_field_definition", "field_definition"}


_PARAMS = {"required_parameter", "optional_parameter"}


def _await_name(node):
    """`await(x)` fuera de contexto await: tree-sitter da await_expression, tsc una llamada
    al identificador `await` (solo si sigue un `(`, también `await<T>(x)`; `await x` es
    siempre await). Contexto await como en tsc: función async, `static {}` o el nivel
    superior de un módulo; una función no async o el inicializador de un campo lo cortan.
    Una clave computada y un decorador (de campo o de parámetro) se evalúan fuera de su dueño."""
    args = [c for c in node.named_children if c.type != "comment"]
    arg = args[0] if args else None
    if arg is not None and arg.type == "type_assertion":   # `await<number>(5)`
        arg = arg.named_children[-1] if arg.named_children else None
    if arg is None or not arg.text.startswith(b"("):     # también `await(a)(b)`, `await(a).f()`
        return None
    child, p, skip_fn = node, node.parent, False
    while p is not None:
        outside = (p.child_by_field_name("name") == child or p.child_by_field_name("property") == child
                   or child.type == "decorator")
        if child.type == "decorator" and p.type in _PARAMS:
            skip_fn = True                     # decorador de parámetro: fuera de su función
        if p.type == "class_static_block":
            return None
        if p.type in _FN_LIKE:
            if skip_fn:
                skip_fn = False
            elif not outside:
                return None if any(c.type == "async" for c in p.children) else "await"
        elif p.type in _FIELDS and not outside:
            return "await"
        child, p = p, p.parent
    # nivel superior: en un módulo (import/export) es contexto await, en un script no
    is_module = any(c.type in ("import_statement", "export_statement") for c in child.children)
    return None if is_module else "await"


_CALL_NODES = {"call_expression": _callee_name, "new_expression": _new_name,
               "await_expression": _await_name,
               "jsx_opening_element": _jsx_name, "jsx_self_closing_element": _jsx_name}


def _outer_decorators(node) -> list:
    """Decoradores que tsc (y `ast` en Python) cuelgan del nodo y tree-sitter TS deja fuera:
    los de un método son hermanos previos en class_body; los de `@D() export class C`
    cuelgan del export_statement."""
    out = []
    if node.type == "method_definition":
        prev = node.prev_sibling
        while prev is not None and prev.type in ("decorator", "comment"):
            if prev.type == "decorator":
                out.append(prev)
            prev = prev.prev_sibling
    elif node.type in ("class_declaration", "abstract_class_declaration") \
            and node.parent is not None and node.parent.type == "export_statement":
        out = [c for c in node.parent.children if c.type == "decorator"]
    return out


def _calls_in(node, extra=()) -> list[str]:
    """Todos los nombres llamados dentro del subárbol (incluye anidados, como el oráculo)."""
    out: list[str] = []
    seen: set[str] = set()
    stack = [node, *extra]
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
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "internal_module": "namespace",
    "module": "namespace",
}
_TYPE_KINDS = {"interface", "type", "enum", "namespace"}

# TS/JS idiomático declara funciones como variables u objetos de funciones, no con
# `function`: `const Page = () => …`, `const load = useCallback(() => …)`,
# `export const api = { jobs: () => get("/api/jobs") }`. Sin esto, en un frontend React
# real casi nada era un símbolo (medido en NEXUS: el trace frontend→backend no cruzaba).
# MISMA regla en el oráculo tsc (benchmark/ts_oracle.js): VariableDeclaration /
# PropertyAssignment cuyo initializer es arrow/function, o una llamada que envuelve una
# (patrón useCallback/useMemo/memo).
_FN_VALUES = {"arrow_function", "function_expression", "generator_function"}
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


# `class C\u0032` se llama C2 para tsc; un identificador no admite otras barras
_BS_U = chr(92) + "u"
_ESCAPE = re.compile(r"\\u(?:\{([0-9a-fA-F]+)\}|([0-9a-fA-F]{4}))")
# escapes de un literal string JS: \xHH, \uHHHH, \u{H…}, continuación de línea (`\` + salto
# → nada) y `\c` → c (no los de control)
_STR_ESC = re.compile(r"\\x([0-9a-fA-F]{2})|\\u(?:\{([0-9a-fA-F]+)\}|([0-9a-fA-F]{4}))"
                      "|\\\\(\r\n|[\r\n  ])|\\\\([^bfnrtv0-9xu\r\n  ])")


def _chr(hexdigits: str) -> str:
    """chr de un escape; fuera de rango (`\\u{110000}`, sintaxis inválida) no revienta el archivo."""
    code = int(hexdigits, 16)
    return chr(code) if code <= 0x10FFFF else "�"


def _is_constructor_key(name_node) -> bool:
    r"""`"constructor"() {}` en una clase es el constructor (ES2015, tsc), también con
    escapes (`"\x63onstructor"`); un escape de control (`\n`…) nunca da esa cadena."""
    if name_node.type != "string":
        return False
    inner = name_node.text.decode("utf-8", "replace")[1:-1]
    val = _STR_ESC.sub(lambda m: "" if m.group(4) else (
        m.group(5) or _chr(m.group(1) or m.group(2) or m.group(3))), inner)
    return val == "constructor"


def _identifiers(node) -> list[str]:
    """Identificadores de un `nested_identifier`, en orden."""
    if node.type in ("identifier", "property_identifier"):
        return [node.text.decode("utf-8", "replace")]
    return [s for ch in node.children for s in _identifiers(ch)]


def extract_from_tree_sitter(content: str, file_path: str, language: str) -> list[Capsule]:
    grammar = "javascript" if language == "javascript" else (
        "tsx" if str(file_path).endswith(".tsx") else "typescript")
    tree = _parser(grammar).parse(content.encode("utf-8"))
    lines = content.split("\n")
    caps: list[Capsule] = []
    cols: list[int] = []   # columna de cada cápsula, para desempatar ids

    def emit(name: str, kind: str, node) -> None:
        if _BS_U in name and not name.startswith(("'", '"', "[")):
            name = _ESCAPE.sub(lambda m: _chr(m.group(1) or m.group(2)), name)
        decos = _outer_decorators(node)
        start = node.start_point[0] + 1
        if kind == "class" and decos:
            # `@D() export class C` / `export @D() class C`: como tsc, empieza en el primer
            # modificador (el `@` o el `export`), como una clase decorada sin export
            start = node.parent.start_point[0] + 1
        elif (kind == "class" and node.prev_sibling is not None
              and node.prev_sibling.type == "expression_statement" and node.prev_sibling.text == b"export"
              and any(c.type == "decorator" for c in node.children)):
            # `export⏎@D()⏎class C`: tree-sitter da `export` suelto (palabra reservada, nunca
            # una expresión válida) + clase; tsc una clase exportada que empieza en `export`
            start = node.prev_sibling.start_point[0] + 1
        elif (node.type == "method_definition" and node.prev_sibling is not None
              and node.prev_sibling.type in _FIELDS
              and node.prev_sibling.text in (b"get", b"set")):
            # `get⏎x() {}`: tree-sitter da campo `get` + método; tsc un accessor desde `get`
            start = node.prev_sibling.start_point[0] + 1
        elif node.type == "abstract_class_declaration":
            # `abstract⏎class B {}`: por ASI tsc no la ve abstracta y empieza en `class`
            tok = {c.type: c for c in node.children}
            if "abstract" in tok and "class" in tok and tok["abstract"].end_point[0] != tok["class"].start_point[0]:
                start = tok["class"].start_point[0] + 1
        end = node.end_point[0] + 1
        is_type = kind in _TYPE_KINDS
        ctype = "type_def" if is_type else kind
        body = "\n".join(lines[start - 1:end])
        cols.append(node.start_point[1])
        caps.append(Capsule(
            id=f"{file_path}:{start}:{name}",
            type=ctype, name=name, file_path=file_path,
            start_line=start, end_line=end,
            language=language, signature=f"{kind} {name}",
            # un tipo no tiene aristas: `namespace` agregaría las de los símbolos que contiene
            content=body[:3000], calls=[] if is_type else _calls_in(node, decos),
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
            # `declare module "pkg"` nombra un paquete ajeno, no un símbolo
            if name_node is None or (kind == "namespace" and name_node.type == "string"):
                pass
            elif (n.type == "interface_declaration" and n.children
                  and n.children[0].end_point[0] != name_node.start_point[0]):
                pass   # `interface⏎I⏎{}`: por ASI tsc ve identificadores y un bloque
            elif name_node.type == "nested_identifier":
                # `namespace A.B.C` declara A, B y C (como tsc); los segmentos son
                # identifier aunque haya comentarios entre ellos
                for seg in _identifiers(name_node):
                    emit(seg, kind, n)
            elif (kind == "method" and n.parent is not None and n.parent.type == "class_body"
                  and _is_constructor_key(name_node)
                  and not any(c.type in ("*", "get", "set") for c in n.children)):
                emit("constructor", kind, n)   # `*"constructor"` o `get "constructor"` no lo son
            else:
                emit(name_node.text.decode("utf-8", "replace"), kind, n)
        stack.extend(n.children)
    # Mismo nombre en la misma línea (get/set, `[{run}, {run}]`, `namespace A.A`): el índice va
    # por id. El primero en el texto conserva el id de siempre; los demás llevan su columna.
    by_id: dict[str, list[int]] = {}
    for i, c in enumerate(caps):
        by_id.setdefault(c.id, []).append(i)
    for base, idxs in by_id.items():
        if len(idxs) > 1:
            idxs.sort(key=lambda i: cols[i])
            used = {base}
            for i in idxs[1:]:
                cid, k = f"{base}:{cols[i]}", 1
                while cid in used or cid in by_id:
                    cid, k = f"{base}:{cols[i]}:{k}", k + 1
                used.add(cid)
                caps[i].id = cid
    return caps
