"""GraphQuery — respuestas estructurales DETERMINISTAS con prueba citable, sin LLM.

El cerebro determinista del código: dado el grafo de cápsulas (AST), responde las
preguntas estructurales —dónde se define, quién llama, qué llama, qué se rompe, y
cómo fluye el control de A a B— al instante, sin alucinar, y devolviendo la PRUEBA
(cada hecho = símbolo + archivo:línea + la arista que lo justifica). Cero tokens LLM.

Funciona sobre un store de cápsulas de UNO o VARIOS repos (cross-repo: el grafo se
resuelve por nombre, así una arista puede cruzar el límite de un repo). Las aristas
cross-lenguaje (HTTP/RPC) las inyecta un resolver aparte; aquí solo se recorren.

Self-check:  python -m leo_code.core.graphquery
"""

from __future__ import annotations

import builtins
import sys
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cite:
    """Una cita verificable: el símbolo y dónde está, comprobable abriendo el archivo."""
    name: str
    type: str
    file: str
    line: int
    repo: str = ""

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}"
        return f"{self.name} ({self.type}) @ {loc}" + (f" [{self.repo}]" if self.repo else "")


@dataclass
class Proof:
    """Respuesta estructural + las citas que la prueban. `kind` describe la relación."""
    kind: str
    query: str
    cites: list[Cite] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (origen, destino) por arista usada

    @property
    def found(self) -> bool:
        return bool(self.cites)

    def render(self) -> str:
        if not self.cites:
            return f"[{self.kind}] no results for '{self.query}'."
        head = f"[{self.kind}] {self.query} — {len(self.cites)} result(s), with proof:"
        lines = [head] + [f"  · {c}" for c in self.cites]
        if self.edges:
            lines.append("  edges: " + " → ".join(
                dict.fromkeys([self.edges[0][0]] + [e[1] for e in self.edges])))
        return "\n".join(lines)


_JS_FAMILY = {"javascript", "typescript", "js", "ts", "jsx", "tsx"}


def _family(c) -> str:
    lang = (getattr(c, "language", "") or "").lower()
    return "js" if lang in _JS_FAMILY else lang


def _same_family(a, b) -> bool:
    fa, fb = _family(a), _family(b)
    return not fa or not fb or fa == fb   # sin lenguaje conocido → no se filtra


def _xlang_targets(c) -> set:
    return {_bare(x.get("to", "")) for x in ((getattr(c, "properties", None) or {}).get("xlang_calls") or [])}


def _bare(name: str) -> str:
    """Nombre base sin calificador de clase/módulo: 'A.method' → 'method'."""
    return name.split(".")[-1]


def _norm(path: str) -> str:
    return (path or "").replace("\\", "/")


_BUILTINS = frozenset(dir(builtins))
_NONE: dict = {}   # default de .get() compartido: `.get(k, {})` crearía un dict por llamada (GC, chequeo (e))
# No son defs llamables. Por exclusión y no por lista: el clasificador reetiqueta defs
# (middleware, model, endpoint…) y una lista cerrada las dejaba sin resolver.
_NOT_DEFS = frozenset({"module", "attribute", "variable", "constant", "file_header",
                       "entrypoint", "document", "image"})


class _PyScope:
    """Resolución de llamadas Python por ámbito del archivo + tabla de imports.

    Es la regla IMPORT de PyCG (Salis et al., ICSE 2021) sin el resto del análisis:
    `go()` con `from util import run as go` va a util.run; `u.run()` con `import util as u`
    también; `foo()` definida en el mismo archivo va a esa def. Lo que no se puede
    decidir así (receptores `self`/`obj`, nombres sin enlace) devuelve None → el grafo
    sigue uniéndolo por nombre, como antes: resolver nunca quita una arista posible.
    """

    def __init__(self, caps):
        self.files: set[str] = set()
        self.top = defaultdict(lambda: defaultdict(list))   # archivo → nombre → defs top-level
        self.binds = defaultdict(dict)                      # archivo → nombre local → enlace
        pkgs = set()
        for c in caps:
            if (getattr(c, "language", "") or "") != "python":
                continue
            f = _norm(c.file_path)
            self.files.add(f)
            if f.endswith("/__init__.py"):
                pkgs.add(f.rsplit("/", 1)[0])
            props = c.properties or {}
            if "bind" in props:
                self.binds[f][props["bind"][0]] = props["bind"]
            elif c.type not in _NOT_DEFS and "class" not in props and c.content:
                self.top[f][c.name].append(c)
        # módulo con puntos → archivos. Sin raíces de sys.path: vale cualquier sufijo de la
        # ruta que empiece fuera de un paquete (su carpeta no tiene __init__.py).
        # ponytail: un __init__.py vacío no deja cápsulas → esa carpeta parece raíz y puede
        # sobrar algún candidato; se uniría a todos, como por nombre.
        # valor str (un archivo, lo normal) o tupla (varios): ~34k claves en django y una
        # lista por clave eran asignaciones que el GC cuenta dentro del chequeo (e)
        self.mods: dict[str, str | tuple] = {}
        for f in self.files:
            parts = f[:-3].split("/") if f.endswith(".py") else []
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            for k in range(1, len(parts) + 1):
                if "/".join(parts[:-k]) not in pkgs:
                    key = ".".join(parts[-k:])
                    prev = self.mods.get(key)
                    if prev is None:
                        self.mods[key] = f
                    else:
                        self.mods[key] = ((prev,) if isinstance(prev, str) else prev) + (f,)
        self.tops = {m.split(".")[0] for m in self.mods}
        for d in (self.top, self.binds, *self.top.values()):
            d.default_factory = None            # ya construidos: leer una clave que falta no la crea
        self._memo: dict[str, dict[str, list | None]] = {}   # archivo → llamada → destinos

    def _mod_files(self, mod: str, level: int, here: str) -> list | None:
        """Archivos del módulo: lista, [] = fuera del repo, None = no se sabe."""
        if level:
            base = here.rsplit("/", level)[0]
            path = base + ("/" + mod.replace(".", "/") if mod else "")
            return [f for f in (path + ".py", path + "/__init__.py") if f in self.files] or None
        hit = self.mods.get(mod)
        if hit:
            return [hit] if isinstance(hit, str) else hit
        top = mod.split(".")[0]
        return [] if top in sys.stdlib_module_names or top not in self.tops else None

    def _in_module(self, files: list, attr: str, depth: int) -> list | None:
        """Defs `attr` de esos archivos, siguiendo re-exports (`from .b import run` en un __init__)."""
        out, external = [], False
        for f in files:
            if attr in self.top.get(f, _NONE):
                out += self.top[f][attr]
            elif depth < 4 and attr in self.binds.get(f, _NONE):
                r = self._bind_targets(self.binds[f][attr], f, depth + 1)
                out += r or []
                external |= r == []
        return out or ([] if external else None)

    def _bind_targets(self, b: list, here: str, depth: int = 0) -> list | None:
        """Defs a las que apunta llamar un nombre importado."""
        _, mod, attr, level = b
        if not attr:
            return None                     # `import x` y luego `x()`: no es una def
        files = self._mod_files(mod, level, here)
        return files if not files else self._in_module(files, attr, depth)

    def _bind_module(self, b: list, here: str) -> list | None:
        """Archivos del módulo al que apunta un nombre importado (`import a as X`, `from a import b`)."""
        _, mod, attr, level = b
        return self._mod_files(".".join(x for x in (mod, attr) if x), level, here)

    def targets(self, caller, name: str, recv: str) -> list | None:
        """Destinos de una llamada de `caller`: defs exactas, [] = va fuera del repo,
        None = no se puede decidir aquí (se une por nombre)."""
        by_name, resolved = [], {}
        self.resolve(caller, [(name, recv)], by_name, resolved)
        return None if by_name else list(resolved.values())

    def resolve(self, caller, forms, by_name: list, resolved: dict) -> None:
        """`targets` de cada forma de llamada de `caller`: el nombre va a `by_name` si no se
        decide, sus defs a `resolved` (id → def) si sí. Ruta normalizada una vez y sin
        objetos por llamada: corre por cada símbolo al reconstruir el grafo (chequeo (e))."""
        here = _norm(caller.file_path)
        if here not in self.files:
            by_name += [n for n, _ in forms]
            return
        lb = (caller.properties or {}).get("local_binds")
        local = {b[0]: b for b in lb} if lb else {}
        top = self.top.get(here, _NONE)
        binds = self.binds.get(here, _NONE)
        memo = self._memo.get(here)
        if memo is None:
            memo = self._memo[here] = {}
        for name, recv in forms:
            if recv == "" and name not in local and name not in top and name not in binds:
                if name not in _BUILTINS:
                    by_name.append(name)
                continue
            if recv and recv not in local and recv not in binds:
                by_name.append(name)          # self.foo(), obj.foo(), a.b.foo(): por nombre
                continue
            if (recv or name) in local:       # import dentro de la función: tapa al del archivo
                t = self._bound(local[recv or name], name, recv, here)
            else:
                # mismo archivo + receptor + nombre → mismo destino. Clave str: el GC no la rastrea
                key = f"{recv}.{name}" if recv else name
                if key not in memo:
                    if recv == "" and name in top:
                        memo[key] = top[name]
                    else:
                        b = binds.get(recv or name) if recv not in top else None
                        memo[key] = self._bound(b, name, recv, here) if b else None
                t = memo[key]
            if t is None:
                by_name.append(name)
            else:
                for d in t:
                    resolved[d.id] = d

    def _bound(self, b: list, name: str, recv: str, here: str) -> list | None:
        """Destinos de `name()` (recv '') o `recv.name()` cuando el nombre clave viene del import `b`."""
        if not recv:
            return self._bind_targets(b, here)
        files = self._bind_module(b, here)
        return files if not files else self._in_module(files, name, 0)


class GraphQuery:
    """Índices deterministas sobre un store de cápsulas (id -> Capsule)."""

    def __init__(self, capsules: dict):
        self.caps = capsules or {}
        # defaultdict al construir: `setdefault(k, [])` crea una lista por llamada aunque la
        # clave exista, y esa basura dispara pasadas del GC dentro del chequeo (e).
        self.by_name: dict[str, list] = defaultdict(list)
        self.callers: dict[str, list] = defaultdict(list)   # callee_name -> [cápsulas que lo llaman]
        for c in self.caps.values():
            self.by_name[c.name].append(c)
            self.by_name[_bare(c.name)].append(c)
        # Cada llamada con forma conocida se intenta resolver (_PyScope). Resuelta → arista
        # exacta caller→def (`_res`, por nombre de la def); sin resolver → por nombre, como
        # siempre. `calls` sin forma (otros lenguajes, refs que añade refgraph) → por nombre.
        self._scope = scope = _PyScope(self.caps.values())
        self._res: dict[str, list] = defaultdict(list)   # nombre base de la def → callers resueltos
        pending, resolved = [], {}              # reutilizados: menos objetos → menos pasadas del GC
        for c in self.caps.values():
            calls = getattr(c, "calls", None) or []
            props = c.properties or {}
            forms = props.get("call_forms")
            if forms is None:
                by_name = calls
            else:
                pending.clear(); resolved.clear()
                pending += calls[props.get("n_calls", len(calls)):]
                scope.resolve(c, forms, pending, resolved)
                for d in resolved.values():
                    self._res[_bare(d.name)].append(c)
                by_name = pending
            for callee in by_name:
                self.callers[callee].append(c)
                self.callers[_bare(callee)].append(c)
        # Familias de lenguaje por nombre, precomputadas: _edge_ok se llama UNA VEZ POR
        # ARISTA y resolverlas ahí costaba un _resolve() (con sort) por arista — a escala
        # real (296k símbolos, nombres muy repetidos) eso disparó who_calls ×54 e impact
        # ×42 y tumbó el SLA del chequeo (d). Aquí es O(1) por arista.
        self._fams: dict[str, set] = defaultdict(set)
        for c in self.caps.values():
            if self._is_def(c):
                fam = _family(c)
                self._fams[c.name].add(fam)
                self._fams[_bare(c.name)].add(fam)
        for d in (self.by_name, self.callers, self._res, self._fams):
            d.default_factory = None            # ya construidos: leer una clave que falta no la crea

    # ---- helpers ----
    def _cite(self, c) -> Cite:
        return Cite(c.name, c.type, c.file_path or "?", getattr(c, "start_line", 0) or 0,
                    repo=(c.properties or {}).get("repo", ""))

    @staticmethod
    def _is_def(c) -> bool:
        """¿Es una definición real (no un import / pseudo-cápsula)?"""
        sig = (getattr(c, "signature", "") or "").lstrip()
        if sig.startswith(("from ", "import ")):
            return False
        return c.type in ("function", "class", "method", "model", "endpoint",
                          "component", "route", "async_function") and bool(c.content)

    def _resolve(self, name: str) -> list:
        """Cápsulas cuyo nombre (cualificado o base) coincide. Prioriza las
        DEFINICIONES reales sobre imports/pseudo-cápsulas → la prueba cita la def."""
        hits = self.by_name.get(name) or self.by_name.get(_bare(name)) or []
        seen, out = set(), []
        for c in hits:
            if c.id not in seen:
                seen.add(c.id); out.append(c)
        out.sort(key=lambda c: 0 if self._is_def(c) else 1)
        return out

    # La resolución es por NOMBRE: en un repo mixto `d.get()` de Python contaba como
    # caller de un `get()` de TypeScript (medido en NEXUS: `get` con 25 "callers").
    # Una arista solo vale dentro de la misma familia de lenguaje o si es HTTP explícita
    # (boundary → properties["xlang_calls"]). En repos de un solo lenguaje no cambia nada.
    def _edge_ok(self, caller, callee: str) -> bool:
        fams = self._fams.get(callee) or self._fams.get(_bare(callee))
        if not fams:
            return True                      # callee externo (sin definición indexada)
        caller_fam = _family(caller)
        if not caller_fam or "" in fams or caller_fam in fams:
            return True
        return _bare(callee) in _xlang_targets(caller)   # solo aristas HTTP explícitas

    def _callers_of(self, name: str) -> list:
        callers = self.callers.get(name) or self.callers.get(_bare(name)) or []
        return [c for c in callers if self._edge_ok(c, name)] + self._res.get(_bare(name), [])

    def _split(self, c, forms, calls) -> tuple[list, Iterable]:
        """(nombres que van por nombre, defs resueltas) de las llamadas de `c`. Los nombres
        de `calls` sin forma (refs que añaden refgraph/boundary) van por nombre."""
        by_name = calls[(c.properties or {}).get("n_calls", len(calls)):]
        resolved = {}
        self._scope.resolve(c, forms, by_name, resolved)
        return by_name, resolved.values()

    def _callees_of(self, c) -> list[tuple[str, list]]:
        """(nombre llamado, defs destino) de `c`: las resueltas con su def exacta, el resto por nombre."""
        calls = getattr(c, "calls", None) or []
        forms = (c.properties or {}).get("call_forms")
        if forms is None:
            return [(n, self._resolve(n)) for n in dict.fromkeys(calls)]
        by_name, resolved = self._split(c, forms, calls)
        return [(d.name, [d]) for d in resolved] + [(n, self._resolve(n)) for n in dict.fromkeys(by_name)]

    # ---- queries deterministas ----
    def where(self, name: str) -> Proof:
        return Proof("where", name, [self._cite(c) for c in self._resolve(name)])

    def who_calls(self, name: str, limit: int = 50) -> Proof:
        callers = self._callers_of(name)
        seen, uniq = set(), []
        for c in callers:
            if c.id not in seen:
                seen.add(c.id); uniq.append(c)
        return Proof("who_calls", name,
                     [self._cite(c) for c in uniq[:limit]],
                     edges=[(c.name, name) for c in uniq[:limit]])

    def callees(self, name: str, limit: int = 50) -> Proof:
        targets = self._resolve(name)
        if not targets:
            return Proof("callees", name)
        c = targets[0]
        out, edges, seen = [], [], set()
        for _, ts in self._callees_of(c):
            for t in ts:
                if t.id in seen:
                    continue
                seen.add(t.id)
                out.append(self._cite(t)); edges.append((c.name, t.name))
                if len(out) >= limit:
                    break
        return Proof("callees", name, out, edges)

    def impact(self, name: str, limit: int = 200) -> Proof:
        """Cierre transitivo de quién se rompe si cambias `name` (callers de callers…)."""
        roots = self._resolve(name)
        start = roots[0].name if roots else name
        seen, q, order, edges = {_bare(start)}, deque([start]), [], []
        while q:
            cur = q.popleft()
            for caller in self._callers_of(cur):
                key = _bare(caller.name)
                if key not in seen:
                    seen.add(key)
                    order.append(caller); edges.append((caller.name, cur))
                    q.append(caller.name)
            if len(order) >= limit:
                break
        return Proof("impact", name, [self._cite(c) for c in order], edges)

    def trace(self, src: str, dst: str, max_depth: int = 12) -> Proof:
        """Camino de llamadas más corto src → dst (BFS), con cada salto citado.

        Es el "¿cómo fluye de A a B?": devuelve la cadena de funciones que conecta
        ambos extremos. Funciona cross-repo y cross-lenguaje si las aristas existen.
        """
        src_caps = self._resolve(src)
        if not src_caps:
            return Proof("trace", f"{src} → {dst}")
        dst_bare = _bare(dst)
        # adyacencia: nombre -> set(callees por nombre)
        start_names = {c.name for c in src_caps} | {_bare(c.name) for c in src_caps}
        # BFS sobre nombres siguiendo `calls`
        prev: dict[str, str | None] = {n: None for n in start_names}
        q = deque(start_names)
        hit = None
        depth = {n: 0 for n in start_names}
        while q:
            cur = q.popleft()
            if depth[cur] > max_depth:
                continue
            if _bare(cur) == dst_bare and cur not in start_names:
                hit = cur; break
            for c in self._resolve(cur):
                for callee, _ in self._callees_of(c):
                    if not self._edge_ok(c, callee):
                        continue
                    if _bare(callee) == dst_bare:
                        prev[callee] = cur; hit = callee; q.clear(); break
                    if callee not in prev:
                        prev[callee] = cur; depth[callee] = depth[cur] + 1
                        q.append(callee)
                if hit:
                    break
            if hit:
                break
        if not hit:
            return Proof("trace", f"{src} → {dst}")
        # reconstruir camino
        path, cur = [], hit
        while cur is not None:
            path.append(cur); cur = prev.get(cur)
        path.reverse()
        cites, edges = [], []
        for i, n in enumerate(path):
            r = self._resolve(n)
            if r:
                cites.append(self._cite(r[0]))
            if i:
                edges.append((path[i - 1], n))
        return Proof("trace", f"{src} → {dst}", cites, edges)


# ----------------------------------------------------------------------------
def _demo():
    """Self-check determinista con un grafo sintético. assert-based, sin frameworks."""
    from leo_code.core.parser import Capsule

    def cap(name, calls, file="a.py", line=1, t="function"):
        return Capsule(id=name, type=t, name=name, file_path=file, start_line=line,
                       end_line=line + 2, language="python", signature=f"def {name}()",
                       content="", calls=calls)

    # button -> fetchUser -> apiGetUser -> queryDb -> usersTable
    caps = {c.name: c for c in [
        cap("button", ["fetchUser"], "ui.tsx", 10),
        cap("fetchUser", ["apiGetUser"], "ui.tsx", 20),
        cap("apiGetUser", ["queryDb"], "api.py", 5),
        cap("queryDb", ["usersTable"], "db.py", 30),
        cap("usersTable", [], "db.py", 1, t="model"),
        cap("unrelated", ["fetchUser"], "x.py", 99),
    ]}
    g = GraphQuery(caps)

    # where: prueba con archivo:línea
    w = g.where("apiGetUser")
    assert w.found and w.cites[0].file == "api.py" and w.cites[0].line == 5, w.render()

    # who_calls: fetchUser es llamado por button y unrelated
    wc = {c.name for c in g.who_calls("fetchUser").cites}
    assert wc == {"button", "unrelated"}, wc

    # callees: apiGetUser llama a queryDb
    ce = {c.name for c in g.callees("apiGetUser").cites}
    assert ce == {"queryDb"}, ce

    # impact: cambiar queryDb afecta apiGetUser, fetchUser, button, unrelated
    im = {c.name for c in g.impact("queryDb").cites}
    assert im == {"apiGetUser", "fetchUser", "button", "unrelated"}, im

    # trace: el flujo botón → columna DB, con cada salto citado
    tr = g.trace("button", "usersTable")
    path = [c.name for c in tr.cites]
    assert path == ["button", "fetchUser", "apiGetUser", "queryDb", "usersTable"], path
    # la prueba cita archivos reales en cada salto (cross-archivo: ui.tsx → api.py → db.py)
    files = [c.file for c in tr.cites]
    assert "ui.tsx" in files and "api.py" in files and "db.py" in files, files

    # trace inexistente → sin resultado, sin alucinar
    assert not g.trace("usersTable", "button").found

    print("graphquery self-check OK")
    print(tr.render())


if __name__ == "__main__":
    from leo_code.logging_config import utf8_console
    utf8_console()
    _demo()
