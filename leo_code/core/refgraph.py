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
import sys
import textwrap
from pathlib import Path

from leo_code.core.graphquery import _bare, _is_import, _norm

_DEF_TYPES = {"function", "method", "class", "async_function", "dataclass", "exception", "test",
              "constant", "variable"}


def augment_refs(capsules: dict, scope=None) -> int:
    """Añade aristas de referencia (in-place) a `calls`. Devuelve nº de aristas añadidas.
    Con `scope` (`_PyScope` de las mismas cápsulas) también las de nombres repetidos que
    el archivo importa o define (cualificadas `ruta.py:nombre`)."""
    ix = RefIndex(capsules, scope)
    added = 0
    for c in capsules.values():
        e = ix.edges(c)
        if e:
            c.calls.extend(e); added += len(e)
    return added


def _names(tree) -> set[str]:
    return {n.id if isinstance(n, ast.Name) else n.attr
            for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute))}


class RefIndex:
    """Lo global de las aristas de referencia (cuántas defs tiene cada nombre y en qué
    archivos, los enlaces de import de cada archivo) y el cálculo por cápsula (`edges`).
    `change` lo pasa a la generación siguiente y dice qué nombres cambiaron de estado; `uses`,
    qué cápsulas sin editar dependen de ellos: Guardian.update recalcula solo esas."""

    def __init__(self, capsules: dict, scope=None):
        self.counts: dict[str, int] = {}
        # nombre → archivo que lo define (str, lo normal: un dict por nombre eran ~10 MB en
        # django) o, si son varios, archivo → nº de defs
        self.where: dict[str, str | dict[str, int]] = {}
        for c in capsules.values():
            self._count(c, 1)
        # archivo → nombre local → enlace: las tablas de _PyScope, compartidas hasta un change
        self.binds: dict[str, dict] = scope.binds if scope is not None else {}
        if scope is None:
            for c in capsules.values():
                self._bind(c)
        self.unique = {n for n, k in self.counts.items() if k == 1}
        self.scope = scope
        self._parsed: dict[str, frozenset | None] = {}  # id → nombres, si no trae `refs` guardadas
        self._main: dict[str, set] = {}                 # archivo → nombres de su bloque __main__

    def _count(self, c, sign: int) -> None:
        if c.type in _DEF_TYPES and not _is_import(c):
            # una cadena por archivo, no por cápsula: 38k copias eran 7 MB en django
            b, f = _bare(c.name), sys.intern(_norm(c.file_path))
            old = self.counts.get(b, 0)
            k = old + sign
            if not k:
                del self.counts[b], self.where[b]
                return
            self.counts[b] = k
            w = self.where.get(b)
            if w is None or w == f:
                self.where[b] = f
                return
            if isinstance(w, str):
                w = self.where[b] = {w: old}
            w[f] = w.get(f, 0) + sign
            if not w[f]:
                del w[f]
            if len(w) == 1:
                self.where[b] = next(iter(w))

    def _defined_in(self, n: str):
        w = self.where.get(n, ())
        return (w,) if isinstance(w, str) else w

    def _bind(self, c) -> None:
        props = c.properties or {}
        if "bind" in props and (getattr(c, "language", "") or "") == "python":
            self.binds.setdefault(_norm(c.file_path), {})[props["bind"][0]] = props["bind"]

    def _state(self, n: str) -> tuple:
        return min(self.counts.get(n, 0), 2), tuple(sorted(self._defined_in(n)))

    def change(self, gone, came) -> set[str]:
        """Pasa de las cápsulas `gone` a `came` (todas las de los archivos cambiados, viejas y
        nuevas). Devuelve los nombres cuyo estado cambió: único/repetido o archivos que lo definen."""
        gone, came = list(gone), list(came)
        if self.scope is not None and self.binds is self.scope.binds:
            self.binds = dict(self.binds)    # no tocar las tablas de _PyScope
        keys = {_bare(c.name) for c in gone + came if c.type in _DEF_TYPES}
        before = {n: self._state(n) for n in keys}
        for c in gone:
            self._count(c, -1)
            self._parsed.pop(c.id, None)
            self.binds.pop(_norm(c.file_path), None)
            self._main.pop(c.file_path, None)
        for c in came:
            self._count(c, 1)
            self._parsed.pop(c.id, None)
            self._main.pop(c.file_path, None)
            self._bind(c)
        dirty = {n for n in keys if self._state(n) != before[n]}
        for n in dirty:
            if self.counts.get(n) == 1:
                self.unique.add(n)
            else:
                self.unique.discard(n)
        return dirty

    def aliased_in(self, dirty: set) -> set[str]:
        """Archivos con un `from m import x as y` de un `x` de `dirty`: su arista va a la def `x`."""
        return {f for f, bs in self.binds.items() if any(b[2] in dirty for b in bs.values())}

    def uses(self, c, dirty: set, aliased_in: set) -> bool:
        """¿Cambian las aristas de `c` (sin editar) si cambia el estado de los nombres `dirty`?"""
        if _norm(c.file_path) in aliased_in:
            return True
        props = c.properties or {}
        lb = props.get("local_binds")
        if lb and any(b[2] in dirty for b in lb):
            return True
        stored = props.get("refs")
        if stored is not None:
            # subcadena primero: casi nunca está y evita partir el texto de cada cápsula
            if any(n in stored for n in dirty) and not dirty.isdisjoint(stored.split()):
                return True
        elif c.content and not _is_import(c):
            names = self._names_of(c)
            if names and not dirty.isdisjoint(names):
                return True
        return self._is_main_user(c) and not dirty.isdisjoint(self._main_names(c.file_path))

    def _names_of(self, c):
        stored = (c.properties or {}).get("refs")   # Python: guardadas al indexar (parser._store_refs)
        if stored is not None:
            return stored.split()
        if c.id in self._parsed:
            return self._parsed[c.id]
        try:
            out = frozenset(_names(ast.parse(textwrap.dedent(c.content))))
        except SyntaxError:
            out = None
        self._parsed[c.id] = out
        return out

    def _qualified(self, c, names) -> set[str]:
        """`ruta.py:nombre` para los nombres repetidos que el archivo de `c` enlaza."""
        here, scope = _norm(c.file_path), self.scope
        if scope is None or here not in scope.files:
            return set()
        lb = (c.properties or {}).get("local_binds")
        local = {b[0]: b for b in lb} if lb else {}
        binds = self.binds.get(here) or {}
        out = set()
        for nm in names:
            if self.counts.get(nm, 0) < 2:
                continue
            b = local.get(nm) or binds.get(nm)
            if b is not None:
                _, mod, attr, level = b
                # `import m` (sin attr) enlaza un módulo, no una def. `from m import x as y`:
                # la def se llama x. ponytail: un `obj.y` también cuenta como uso de y.
                files = (scope._mod_files(mod, level, here) or ()) if attr else ()
                defs = self._defined_in(attr)
                out.update(f"{f}:{attr}" for f in files if f in defs)
            # la cabecera son las sentencias de módulo: ahí `X = 1` es la def de X, no un uso
            elif here in self._defined_in(nm) and c.type != "file_header":
                out.add(f"{here}:{nm}")
        return out

    # Bloque `if __name__ == "__main__"`: lo ejecuta quien lanza el archivo como script, a
    # menudo una función del propio archivo (`subprocess.run([python, __file__, …])`, el
    # chequeo (f) de audit_formal). Se atribuye a las funciones del archivo que mencionan
    # `__file__`; a todas, o con el resto del código de módulo, era casi todo el repo como
    # dependiente (mediana 477-608 en leo-code).
    @staticmethod
    def _is_main_user(c) -> bool:
        return (c.type in _DEF_TYPES and "__file__" in (c.content or "")
                and (c.file_path or "").endswith(".py"))

    def _main_names(self, fpath: str) -> set:
        hit = self._main.get(fpath)
        if hit is not None:
            return hit
        src = Path(fpath).read_text(encoding="utf-8", errors="replace") if Path(fpath).is_file() else ""
        out: set[str] = set()
        if "__main__" in src:
            try:
                body = ast.parse(src).body
            except SyntaxError:
                body = []
            for stmt in body:
                t = stmt.test if isinstance(stmt, ast.If) else None
                if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__":
                    out |= _names(stmt)
        self._main[fpath] = out
        return out

    def edges(self, c) -> list[str]:
        """Aristas de referencia de `c` que aún no están en `c.calls`, en orden determinista
        (antes, el de un set: el orden del impacto cambiaba entre procesos)."""
        out: list[str] = []
        content = getattr(c, "content", "") or ""
        have = set(c.calls); self_bare = _bare(c.name)
        if content and not _is_import(c):   # un import no es quien usa lo importado
            names = self._names_of(c)
            if names is not None:
                found = self.unique.intersection(names) | self._qualified(c, set(names) - {self_bare})
                found -= have
                found.discard(self_bare)
                out = sorted(found)
                have.update(out)
        if self._is_main_user(c):
            main = self.unique.intersection(self._main_names(c.file_path)) - have
            main.discard(self_bare)
            out += sorted(main)
        return out
