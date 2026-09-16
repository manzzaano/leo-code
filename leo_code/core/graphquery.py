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

from collections import deque
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


class GraphQuery:
    """Índices deterministas sobre un store de cápsulas (id -> Capsule)."""

    def __init__(self, capsules: dict):
        self.caps = capsules or {}
        self.by_name: dict[str, list] = {}
        self.callers: dict[str, list] = {}     # callee_name -> [cápsulas que lo llaman]
        for c in self.caps.values():
            self.by_name.setdefault(c.name, []).append(c)
            self.by_name.setdefault(_bare(c.name), []).append(c)
        for c in self.caps.values():
            for callee in (getattr(c, "calls", None) or []):
                self.callers.setdefault(callee, []).append(c)
                self.callers.setdefault(_bare(callee), []).append(c)
        # Familias de lenguaje por nombre, precomputadas: _edge_ok se llama UNA VEZ POR
        # ARISTA y resolverlas ahí costaba un _resolve() (con sort) por arista — a escala
        # real (296k símbolos, nombres muy repetidos) eso disparó who_calls ×54 e impact
        # ×42 y tumbó el SLA del chequeo (d). Aquí es O(1) por arista.
        self._fams: dict[str, set] = {}
        for c in self.caps.values():
            if self._is_def(c):
                fam = _family(c)
                self._fams.setdefault(c.name, set()).add(fam)
                self._fams.setdefault(_bare(c.name), set()).add(fam)

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
        return [c for c in callers if self._edge_ok(c, name)]

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
        for callee in (getattr(c, "calls", None) or []):
            for t in self._resolve(callee):
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
                for callee in (getattr(c, "calls", None) or []):
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
    _demo()
