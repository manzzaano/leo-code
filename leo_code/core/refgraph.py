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

Un nombre ÚNICO en el índice (definido exactamente una vez) se conecta por nombre: así
`_detect_go` se conecta, pero nombres comunes (`run`, `get`, `build`) no inyectan ruido.
Un nombre REPETIDO solo se conecta si el archivo lo importa explícitamente o lo define en
su nivel superior, y entonces como `ruta.py:nombre` (la def de ese módulo, no todas las
homónimas): es la regla de imports de PyCG y la expansión de comodines de pyan (#88).
`TestClient(app)` con varios `app` en el repo antes no dejaba arista.
"""

from __future__ import annotations

import ast
import textwrap

from leo_code.core.graphquery import _bare, _is_import, _norm

_DEF_TYPES = {"function", "method", "class", "async_function", "dataclass", "exception", "test",
              "constant", "variable"}


def augment_refs(capsules: dict, scope=None) -> int:
    """Añade aristas de referencia (in-place) a `calls`. Devuelve nº de aristas añadidas.
    Con `scope` (`_PyScope` de las mismas cápsulas) también las de nombres repetidos que
    el archivo importa o define (cualificadas `ruta.py:nombre`)."""
    counts: dict[str, int] = {}
    where: dict[str, set] = {}            # nombre → archivos que lo definen
    for c in capsules.values():
        if c.type in _DEF_TYPES and not _is_import(c):
            b = _bare(c.name)
            counts[b] = counts.get(b, 0) + 1
            where.setdefault(b, set()).add(_norm(c.file_path))
    unique = {n for n, k in counts.items() if k == 1}

    def _qualified(c, names) -> set[str]:
        """`ruta.py:nombre` para los nombres repetidos que el archivo de `c` enlaza."""
        here = _norm(c.file_path)
        if scope is None or here not in scope.files:
            return set()
        lb = (c.properties or {}).get("local_binds")
        local = {b[0]: b for b in lb} if lb else {}
        binds = scope.binds.get(here) or {}
        out = set()
        for nm in names:
            if counts.get(nm, 0) < 2:
                continue
            b = local.get(nm) or binds.get(nm)
            if b is not None:
                _, mod, attr, level = b
                # `import m` (sin attr) enlaza un módulo, no una def. `from m import x as y`:
                # la def se llama x. ponytail: un `obj.y` también cuenta como uso de y.
                files = (scope._mod_files(mod, level, here) or ()) if attr else ()
                out.update(f"{f}:{attr}" for f in files if f in where.get(attr, ()))
            # la cabecera son las sentencias de módulo: ahí `X = 1` es la def de X, no un uso
            elif here in where.get(nm, ()) and c.type != "file_header":
                out.add(f"{here}:{nm}")
        return out

    def _names(tree) -> set[str]:
        return {n.id if isinstance(n, ast.Name) else n.attr
                for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute))}

    def _refs(tree) -> set[str]:
        return unique.intersection(_names(tree))

    added = 0
    for c in capsules.values():
        content = getattr(c, "content", "") or ""
        if not content or _is_import(c):   # un import no es quien usa lo importado
            continue
        stored = (c.properties or {}).get("refs")   # Python: guardadas al indexar (parser._store_refs)
        if stored is not None:
            names = stored.split()
        else:
            try:
                names = _names(ast.parse(textwrap.dedent(content)))
            except SyntaxError:
                continue
        have = set(c.calls); self_bare = _bare(c.name)
        found = unique.intersection(names) | _qualified(c, set(names) - {self_bare})
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
