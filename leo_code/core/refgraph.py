"""refgraph — completa el grafo con aristas de REFERENCIA (dispatch indirecto).

El grafo de llamadas DIRECTAS pierde edges cuando una función se invoca por dispatch:
`_LANG_DISPATCH = {"go": _detect_go}` luego `_LANG_DISPATCH[lang](caps)`. Ahí `_detect_go`
se REFERENCIA (se guarda en el dict) pero no se llama por nombre. Para que el impacto y la
cobertura sean COMPLETOS (cambiar `_detect_go` afecta a quien lo despacha), añadimos una
arista X→Y cuando el cuerpo de X referencia el nombre de un símbolo definido Y.

Solo para nombres ÚNICOS en el índice (definidos exactamente una vez): así `_detect_go`
(único) se conecta, pero nombres comunes (`run`, `get`, `build`) no inyectan ruido —
mantenemos la precisión del grafo.
"""

from __future__ import annotations

import ast
import textwrap

from leo_code.core.graphquery import _bare

_DEF_TYPES = {"function", "method", "class", "async_function", "dataclass", "exception", "test"}


def augment_refs(capsules: dict) -> int:
    """Añade aristas de referencia (in-place) a `calls`. Devuelve nº de aristas añadidas."""
    counts: dict[str, int] = {}
    for c in capsules.values():
        if c.type in _DEF_TYPES:
            b = _bare(c.name)
            counts[b] = counts.get(b, 0) + 1
    unique = {n for n, k in counts.items() if k == 1}

    def _refs(tree) -> set[str]:
        out = set()
        for n in ast.walk(tree):
            nm = n.id if isinstance(n, ast.Name) else (n.attr if isinstance(n, ast.Attribute) else None)
            if nm in unique:
                out.add(nm)
        return out

    added = 0
    # (1) referencias en el cuerpo de cada cápsula
    for c in capsules.values():
        content = getattr(c, "content", "") or ""
        if not content:
            continue
        try:
            tree = ast.parse(textwrap.dedent(content))
        except SyntaxError:
            continue
        have = set(c.calls); self_bare = _bare(c.name)
        for nm in _refs(tree):
            if nm != self_bare and nm not in have:
                c.calls.append(nm); have.add(nm); added += 1

    # (2) referencias a NIVEL DE MÓDULO (tablas de dispatch tipo `_LANG_DISPATCH = {...}`):
    # se atribuyen a todas las funciones del mismo archivo (over-aproximación segura: el
    # guardián prefiere avisar de más). Cierra el dispatch por dict que el análisis por
    # nombre no ve de otra forma.
    from pathlib import Path
    files: dict[str, list] = {}
    for c in capsules.values():
        if c.type in _DEF_TYPES and (c.file_path or "").endswith(".py"):
            files.setdefault(c.file_path, []).append(c)
    for fpath, cs in files.items():
        try:
            tree = ast.parse(Path(fpath).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        # statements de módulo que NO son defs/clases (código a nivel de módulo)
        mod_refs: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            mod_refs |= _refs(stmt)
        if not mod_refs:
            continue
        for c in cs:
            have = set(c.calls); self_bare = _bare(c.name)
            for nm in mod_refs:
                if nm != self_bare and nm not in have:
                    c.calls.append(nm); have.add(nm); added += 1
    return added
