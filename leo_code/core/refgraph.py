"""refgraph — completa el grafo con aristas de REFERENCIA (dispatch indirecto).

El grafo de llamadas DIRECTAS pierde edges cuando una función se invoca por dispatch:
`_LANG_DISPATCH = {"go": _detect_go}` luego `_LANG_DISPATCH[lang](caps)`. Ahí `_detect_go`
se REFERENCIA (se guarda en el dict) pero no se llama por nombre. Para que el impacto y la
cobertura sean COMPLETOS (cambiar `_detect_go` afecta a quien lo despacha), añadimos una
arista X→Y cuando el cuerpo de X referencia el nombre de un símbolo definido Y.

Las constantes y variables de módulo son nodos: `_LANG_DISPATCH` referencia `_detect_go`
y quien usa `_LANG_DISPATCH` lo referencia a él, así que la cadena queda entera sin
atribuir la tabla a todas las funciones del archivo. Antes se hacía eso (y con los
imports incluidos): la mediana de dependientes de guard en leo-code era 608, casi todo
el repo; así es 158, con 0 falsos «sin test» frente a coverage.py (28/10).

Solo para nombres ÚNICOS en el índice (definidos exactamente una vez): así `_detect_go`
(único) se conecta, pero nombres comunes (`run`, `get`, `build`) no inyectan ruido —
mantenemos la precisión del grafo.
"""

from __future__ import annotations

import ast
import textwrap

from leo_code.core.graphquery import _bare

_DEF_TYPES = {"function", "method", "class", "async_function", "dataclass", "exception", "test",
              "constant", "variable"}


def _is_import(c) -> bool:
    return (c.signature or "").lstrip().startswith(("from ", "import "))


def augment_refs(capsules: dict) -> int:
    """Añade aristas de referencia (in-place) a `calls`. Devuelve nº de aristas añadidas."""
    counts: dict[str, int] = {}
    for c in capsules.values():
        if c.type in _DEF_TYPES and not _is_import(c):
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
    for c in capsules.values():
        content = getattr(c, "content", "") or ""
        if not content or _is_import(c):   # un import no es quien usa lo importado
            continue
        stored = (c.properties or {}).get("refs")   # Python: guardadas al indexar (parser._store_refs)
        if stored is not None:
            found = unique.intersection(stored.split())
        else:
            try:
                found = _refs(ast.parse(textwrap.dedent(content)))
            except SyntaxError:
                continue
        have = set(c.calls); self_bare = _bare(c.name)
        for nm in found:
            if nm != self_bare and nm not in have:
                c.calls.append(nm); have.add(nm); added += 1

    # Bloque `if __name__ == "__main__"`: lo ejecuta quien lanza el archivo como script, a
    # menudo una función del propio archivo (`subprocess.run([python, __file__, …])`, el
    # chequeo (f) de audit_formal). Se atribuye a las funciones del archivo que mencionan
    # `__file__`; a todas, o con el resto del código de módulo, era casi todo el repo como
    # dependiente (mediana 477-608 en leo-code).
    from pathlib import Path
    files: dict[str, list] = {}
    for c in capsules.values():
        if c.type in _DEF_TYPES and "__file__" in (c.content or "") \
                and (c.file_path or "").endswith(".py"):
            files.setdefault(c.file_path, []).append(c)
    for fpath, cs in files.items():
        src = Path(fpath).read_text(encoding="utf-8", errors="replace") if Path(fpath).is_file() else ""
        if "__main__" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        main_refs: set[str] = set()
        for stmt in tree.body:
            t = stmt.test if isinstance(stmt, ast.If) else None
            if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__":
                main_refs |= _refs(stmt)
        for c in cs:
            have = set(c.calls); self_bare = _bare(c.name)
            for nm in main_refs - have - {self_bare}:
                c.calls.append(nm); added += 1
    return added
