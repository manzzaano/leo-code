"""Guardian — garantía DETERMINISTA de cambios: radio de explosión + cobertura.

Sobre el grafo del código (GraphQuery), sin LLM y con prueba citable:

  • blast_radius(symbol) → qué se ROMPE si cambias el símbolo (cierre transitivo de
    sus llamadores). Cruza lenguajes si las aristas HTTP están cosidas (boundary):
    cambiar un endpoint marca los componentes cliente que lo consumen.
  • test_closure()      → conjunto de símbolos alcanzados por algún test (cobertura).
  • review(changed)     → por cada símbolo cambiado: su radio de explosión, marcando
    qué afectados están CUBIERTOS por tests y cuáles NO (riesgo), todo con file:línea.

Es lo que un revisor-LLM aluciona o se pierde, hecho determinista y verificable.

Self-check:  python -m leo_code.core.guardian
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass, field

from leo_code.core.graphquery import GraphQuery, Cite


@dataclass
class Affected:
    """Un símbolo dentro del radio de explosión, con su estado de cobertura."""
    cite: Cite
    covered: bool          # ¿lo alcanza algún test? (estático: alcanzable, no ejecutado)
    is_test: bool = False  # un test dependiente es cobertura, no riesgo

    def __str__(self) -> str:
        mark = "✓ reached by a test" if self.covered else "✗ NO test"
        return f"{self.cite}  [{mark}]"


@dataclass
class ChangeReport:
    """Resultado de revisar UN símbolo cambiado."""
    symbol: str
    changed_covered: bool
    affected: list[Affected] = field(default_factory=list)
    note: str = ""         # de impact: «stopped at N; more dependents exist»

    @property
    def uncovered(self) -> list[Affected]:
        """Riesgo: dependientes de producto sin test. Nada cubre a un test, así que listar
        los tests aquí era el 86% de las entradas (27/10, leo-code y django)."""
        return [a for a in self.affected if not a.covered and not a.is_test]

    def render(self, shown: int = 40) -> str:
        lines = [f"changing `{self.symbol}`"
                 + ("  [✓ reached by a test]" if self.changed_covered else "  [✗ NO test]")]
        if not self.affected:
            lines.append(f"  → {self.note}" if self.note else "  → breaks nothing that is indexed.")
            return "\n".join(lines)
        risk = self.uncovered
        n_tests = sum(a.is_test for a in self.affected)
        lines.append(f"  → affects {len(self.affected)} symbol(s): {n_tests} test(s) depend on it, "
                     f"{len(self.affected) - n_tests} in code"
                     + (f", {len(risk)} with NO test (risk):" if risk
                        else ", all reached by a test ✓"))
        lines += [f"    · {a.cite}" for a in risk[:shown]]   # orden del BFS: menor profundidad antes
        if len(risk) > shown:
            lines.append(f"    … showing {shown} of {len(risk)}")
        if self.note:
            lines.append(f"  ({self.note})")
        return "\n".join(lines)



def _in_repo(file_path: str | None, root: str | None) -> Path:
    """Ruta del archivo relativa al repo (tal cual si no se sabe el repo o cae fuera)."""
    p = Path(file_path or "")
    if root:
        try:
            return Path(os.path.abspath(p)).relative_to(root)
        except ValueError:
            pass
    return p

@lru_cache(maxsize=1 << 16)
def _test_file(file_path: str | None, root: str | None, cwd: str | None) -> bool:
    """¿Es de test el archivo? Una vez por archivo: django tiene 72k cápsulas en 2,4k
    archivos y `relative_to` por cápsula era casi todo `test_closure`. `cwd` entra en la
    clave porque `_in_repo` resuelve las rutas relativas con `abspath`."""
    from leo_code.guard_hook import _is_test_path
    return _is_test_path(_in_repo(file_path, root))


def _copy(c):
    """Copia con `calls` propia: el guardián aumenta el grafo sin tocar el directo."""
    import copy
    cc = copy.copy(c)
    cc.calls = list(c.calls or [])
    return cc


def _key(c) -> tuple:
    return c.file_path or "?", c.start_line or 0, c.name


class Guardian:
    def __init__(self, capsules: dict, repo: str | None = None):
        # El guardián usa el grafo AUMENTADO con aristas de referencia/dispatch
        # (completitud: cambiar X que se invoca por dict debe marcar a quien lo despacha).
        # Sobre una COPIA de las listas `calls` para NO contaminar el grafo directo y
        # preciso que usan who_calls/trace/where (que se demuestra sound+complete vs ast).
        from leo_code.core.graphquery import _PyScope
        from leo_code.core.refgraph import RefIndex
        aug = {k: _copy(c) for k, c in (capsules or {}).items()}
        scope = _PyScope(aug.values())     # no mira `calls`: vale antes y después de aumentar
        self._refs = ix = RefIndex(aug, scope)
        for c in aug.values():
            c.calls.extend(ix.edges(c))
        self._orig = capsules or {}        # de qué cápsulas salen las copias: update compara con ellas
        self._repo = repo
        self.caps = aug
        self.gq = GraphQuery(aug, scope)
        self._covered: set[str] | None = None
        # test_closure: destinos (ids) de cada nodo alcanzado y de las semillas de cada archivo
        # de test; update solo tira los que pueden haber cambiado (_invalidate)
        self._rows: dict[str, tuple] = {}
        self._seeds: dict[str, tuple] = {}
        self._root = os.path.abspath(repo) if repo else None   # la regla de test mira la ruta DENTRO del repo, no sus carpetas padre
        # cita (archivo, línea, nombre) → su cápsula: la cobertura va por definición
        self._at = {_key(c): c for c in aug.values()}

    def update(self, capsules: dict, touched=()) -> bool:
        """Pasa el guardián a `capsules`, la generación siguiente del mismo repo: copias y
        aristas de referencia nuevas solo para los archivos cambiados (cápsulas nuevas,
        quitadas o en `touched`, ids que link_http_edges mutó en sitio) y para las cápsulas
        que referencian un nombre que pasó de único a repetido o al revés; el grafo, con
        `GraphQuery.update`. Queda igual que `Guardian(capsules, repo)`. Si cambia el
        conjunto de archivos, reconstruye entero. Devuelve True si fue incremental."""
        old, prev = self._orig, self.caps
        changed = {c.file_path for k, c in capsules.items() if old.get(k) is not c}
        if len(old) != len(capsules) or changed:
            changed.update(c.file_path for k, c in old.items() if k not in capsules)
        # cambia el conjunto de archivos → módulos y paquetes de _PyScope: entero (raro)
        if changed and {c.file_path for c in old.values()} != {c.file_path for c in capsules.values()}:
            self.__init__(capsules, self._repo)
            return False
        ix = self._refs
        gone = [c for c in prev.values() if c.file_path in changed]
        came = [_copy(c) for c in capsules.values() if c.file_path in changed]
        dirty = ix.change(gone, came)
        redo = {k for k in touched if k in capsules}
        if dirty:
            alias = ix.aliased_in(dirty)
            redo.update(k for k, c in prev.items()
                        if c.file_path not in changed and ix.uses(c, dirty, alias))
        # Copia nueva para todo el archivo de cada cápsula a rehacer, no `calls` mutadas en
        # sitio: GraphQuery.update quita lo que aportaba cada archivo con sus cápsulas viejas,
        # y así `_at` se rehace por archivo con el mismo «gana la última» que en frío.
        redo_files = changed | {capsules[k].file_path for k in redo}
        new = {c.id: c for c in came}
        aug, fresh = {}, []
        for k, c in capsules.items():
            if c.file_path in redo_files:
                a = new.get(k) or _copy(c)
                a.calls.extend(ix.edges(a))
                fresh.append(a)
            else:
                a = prev[k]
            aug[k] = a
        for c in prev.values():
            if c.file_path in redo_files and self._at.get(_key(c)) is c:
                del self._at[_key(c)]
        self._at.update((_key(c), c) for c in fresh)
        self._orig, self.caps, self._covered = capsules, aug, None
        inc = self.gq.update(aug)
        ix.scope = self.gq._scope
        self._invalidate()
        return inc

    def _invalidate(self) -> None:
        """Tira las filas de test_closure cuyos saltos pueden haber cambiado en el último
        `gq.update`: las cápsulas re-resueltas, quien llama por nombre a uno cuyas defs
        cambiaron (`callers`, `_res`) y las subclases de las clases re-resueltas (su
        constructor heredado, `ctor_hops`). Validado contra fuerza bruta en django: 64
        ediciones, 0 nodos con saltos distintos fuera de esta cota."""
        from leo_code.core.graphquery import _CLASS_TYPES, _norm
        gq = self.gq
        if gq.delta is None:                 # grafo construido entero
            self._rows, self._seeds = {}, {}
            return
        ids, files, names = gq.delta
        hit = set(ids)
        for k in names:
            for lst in (gq.callers.get(k, ()), gq._res.get(k, ())):
                hit.update(c.id for c in lst)
        sc = gq._scope
        todo = [k for k in sc.classes if k.split("\0", 1)[0] in files]
        seen = set(todo)
        while todo:
            for sub in sc.subs.get(todo.pop(), ()):
                if sub not in seen:
                    seen.add(sub); todo.append(sub)
        for k in seen:
            f, name = k.split("\0", 1)
            hit.update(c.id for c in gq.by_name.get(name, ())
                       if c.type in _CLASS_TYPES and _norm(c.file_path) == f)
        seeds = set(files)
        for i in hit:
            self._rows.pop(i, None)
            c = self.caps.get(i)
            if c is not None:
                seeds.add(_norm(c.file_path))
        for f in seeds:
            self._seeds.pop(f, None)

    # ---- cobertura: símbolos alcanzados por algún test ----
    @staticmethod
    def _is_test(c, root: str | None = None) -> bool:
        if c.type == "test":
            return True
        # Mismo criterio que el hook: «test» suelto en el nombre del archivo marcaba
        # producto como test (django: testing.py, testserver.py).
        return ((c.name or "").lower().startswith("test_")
                or _test_file(c.file_path, root, root and os.getcwd()))

    def test_closure(self) -> set[str]:
        """Ids de las definiciones alcanzables desde algún test (transitivo).

        Por definición, con la resolución de llamadas (`_hops`: resueltas → su def; sin
        resolver → todas las homónimas, no se quita una arista incierta; `x.f()` con `x`
        desconocido, solo métodos y funciones de módulos importados). Por nombre, un
        test de un `helper` cubría a todos los `helper` del repo."""
        if self._covered is not None:
            return self._covered
        from leo_code.core.graphquery import _norm
        tests: dict[str, list] = {}
        for c in self.caps.values():
            if self._is_test(c, self._root):
                tests.setdefault(_norm(c.file_path), []).append(c)
        old = self._seeds
        self._seeds = {}
        q: list = []                      # filas por visitar (pila: el orden da igual)
        for f, cs in tests.items():
            r = old.get(f)
            if r is None:
                r = self._seed_row(cs)
            self._seeds[f] = r
            q.append(r)
        seen: set[str] = set()
        rows, caps = self._rows, self.caps
        while q:
            for i in q.pop():
                if i in seen:
                    continue
                seen.add(i)
                r = rows.get(i)
                if r is None:
                    r = rows[i] = self._row(caps[i])
                q.append(r)
        self._covered = seen
        return seen

    def _row(self, d) -> tuple:
        """Ids a los que salta `d` al ejecutarse."""
        hops = self.gq.ctor_hops(d)       # alcanzar una clase no ejecuta todos sus métodos
        if hops is not None:
            return tuple({t.id for t, _, _ in hops})
        return self._seed_row((d,))

    def _seed_row(self, cs) -> tuple:
        """Ids a los que saltan las cápsulas `cs` (las de test, siempre por sus llamadas)."""
        out: set[str] = set()
        for c in cs:
            res, groups = self.gq._hop_groups(c, strict=True)
            out.update(t.id for t in res)
            for g in groups:
                out.update(t.id for t in g)
        return tuple(out)

    def is_covered(self, sym) -> bool:
        """Una cápsula: ¿la alcanza un test? Un nombre: ¿alguna de sus defs?"""
        if not isinstance(sym, str):
            return sym.id in self.test_closure()
        return any(c.id in self.test_closure() for c in self.gq._resolve(sym))

    # ---- radio de explosión + revisión ----
    def review(self, changed_symbol: str, limit: int = 200) -> ChangeReport:
        impact = self.gq.impact(changed_symbol, limit=limit)
        caps = [self._at[(c.file, c.line, c.name)] for c in impact.cites]
        affected = [Affected(c, self.is_covered(cap), self._is_test(cap, self._root))
                    for c, cap in zip(impact.cites, caps)]
        defs = self.gq.defs_named(changed_symbol)
        return ChangeReport(symbol=changed_symbol,
                            changed_covered=(any(map(self.is_covered, defs)) if defs
                                             else self.is_covered(changed_symbol)),
                            affected=affected, note=impact.note)

    def review_many(self, symbols: list[str]) -> list[ChangeReport]:
        return [self.review(s) for s in symbols]

    # ---- diff de git → símbolos cambiados → revisión (PR/CI guardian) ----
    def changed_symbols(self, diff_text: str) -> list[str]:
        """Mapea las líneas cambiadas de un `git diff` a los símbolos (cápsulas) que
        las contienen. Es el puente diff → grafo."""
        import codecs
        import re
        changes: dict[str, set[int]] = {}   # archivo → líneas (lado nuevo) tocadas
        cur, ln = None, 0                   # ln: línea del lado nuevo dentro del hunk
        old_left = new_left = 0             # líneas que quedan del hunk: dentro, nada es cabecera
        for line in diff_text.splitlines():
            if old_left > 0 or new_left > 0:
                # solo + y -: el contexto del hunk (3 líneas) es de funciones vecinas sin tocar
                if line.startswith("+"):
                    changes[cur].add(ln); ln += 1; new_left -= 1
                elif line.startswith("-"):
                    # un borrado no ocupa línea nueva: marca las dos que quedan a sus lados
                    changes[cur].update((ln - 1, ln)); old_left -= 1
                elif line.startswith(" ") or line == "":
                    ln += 1; old_left -= 1; new_left -= 1
                continue                    # «\ No newline at end of file»
            if line.startswith("diff --git"):
                cur = None
            elif line.startswith('+++ "b/'):
                # ruta con caracteres no ASCII o especiales: git la cita con escapes en octal
                raw = line[4:].rstrip("\t").strip()[1:-1]
                cur = codecs.escape_decode(raw.encode("latin-1", "backslashreplace"))[0] \
                    .decode("utf-8", "replace")[2:]
                changes.setdefault(cur, set())
            elif line.startswith("+++ b/"):
                cur = line[6:].strip()
                changes.setdefault(cur, set())
            elif line.startswith("@@") and cur is not None:
                m = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if m:
                    old_left, ln = int(m.group(1) or 1), int(m.group(2))
                    new_left = int(m.group(3) or 1)
        # cápsulas cuyo rango [start,end] solapa con líneas cambiadas del mismo archivo; la
        # ruta del diff es relativa a la raíz de git: se empareja por ruta, no por nombre
        out: list[str] = []
        seen: set[str] = set()
        for c in self.caps.values():
            cf = (c.file_path or "").replace("\\", "/")
            for f, lines in changes.items():
                if cf == f or cf.endswith("/" + f) or f.endswith("/" + cf):
                    lo, hi = getattr(c, "start_line", 0), getattr(c, "end_line", 0)
                    if any(lo <= ln <= hi for ln in lines) and c.name not in seen \
                            and c.type in ("function", "method", "class", "endpoint",
                                           "component", "async_function"):
                        seen.add(c.name); out.append(c.name)
                    break
        return out

    def review_diff(self, diff_text: str) -> list[ChangeReport]:
        return self.review_many(self.changed_symbols(diff_text))


def git_diff(repo: str = ".", staged: bool = False, base: str | None = None) -> str:
    """Devuelve el diff a revisar: staged, working tree, o vs una rama base (PR)."""
    import subprocess
    args = ["git", "-C", repo, "diff", "--unified=3", "--no-color"]
    if base:
        args.append(base)
    elif staged:
        args.append("--cached")
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace").stdout
    except Exception:
        return ""


def guard_repo(repo: str = ".", staged: bool = False, base: str | None = None) -> tuple[list[ChangeReport], dict]:
    """PR/CI guardian end-to-end: indexa, cose cross-lenguaje, revisa el diff.
    Devuelve (reports, resumen). Cero LLM."""
    from leo_code.rag.indexer import Indexer
    from leo_code.core.boundary import link_http_edges
    idx = Indexer()
    idx.build(repo, verbose=False)
    caps = idx.get_capsules()
    link_http_edges(caps)                 # aristas HTTP para impacto cross-lenguaje
    g = Guardian(caps, repo)
    reports = g.review_diff(git_diff(repo, staged, base))
    return reports, summarize(reports)


def summarize(reports: list[ChangeReport]) -> dict:
    """Totales sin repetir: un dependiente de varios símbolos cambiados cuenta una vez
    (sumando, el diff main..dev daba 2.344 «riesgo» para ~41 símbolos distintos)."""
    key = lambda a: (a.cite.file, a.cite.line, a.cite.name)
    return {"changed": len(reports),
            "affected": len({key(a) for r in reports for a in r.affected}),
            "uncovered_risk": len({key(a) for r in reports for a in r.uncovered})}


# ----------------------------------------------------------------------------
def _demo():
    """Self-check: cambio de un endpoint marca el cliente React (cross-lenguaje) sin test."""
    from leo_code.core.parser import Capsule
    from leo_code.core.boundary import link_http_edges

    def cap(name, content, file, t="function", calls=None, lang="python"):
        return Capsule(id=f"{file}:{name}", type=t, name=name, file_path=file, start_line=1,
                       end_line=9, language=lang, signature="", content=content, calls=calls or [])

    caps = {c.id: c for c in [
        cap("Dashboard", "fetch('/api/report')", "web/app.tsx", "component", lang="ts"),
        cap("get_report", "@app.get('/api/report')\ndef get_report(): return build()",
            "api.py", "endpoint", calls=["build"]),
        cap("build", "def build(): return read_db()", "logic.py", calls=["read_db"]),
        cap("read_db", "def read_db(): pass", "db.py", t="model"),
        cap("test_build", "def test_build(): build()", "tests/test_logic.py", t="test", calls=["build"]),
    ]}
    link_http_edges(caps)                 # cose Dashboard → get_report (HTTP)
    g = Guardian(caps)

    # `build` está cubierto (test_build lo llama); `read_db` también (via build).
    assert g.is_covered("build") and g.is_covered("read_db")
    # `get_report` NO tiene test; el `Dashboard` (cliente React) tampoco.
    assert not g.is_covered("get_report") and not g.is_covered("Dashboard")

    # Cambiar `get_report`: impacto debe incluir el Dashboard (cross-lenguaje) y marcarlo sin test.
    rep = g.review("get_report")
    names = {a.cite.name for a in rep.affected}
    assert "Dashboard" in names, names                      # cruzó el límite HTTP
    dash = next(a for a in rep.affected if a.cite.name == "Dashboard")
    assert not dash.covered                                  # rotura no cubierta por tests
    # Cambiar `read_db`: rompe build (con test) → cubierto.
    rep2 = g.review("read_db")
    assert any(a.cite.name == "build" and a.covered for a in rep2.affected)

    print("guardian self-check OK — radio de explosión + cobertura + cross-lenguaje")
    print(rep.render())


if __name__ == "__main__":
    from leo_code.logging_config import utf8_console
    utf8_console()
    # CLI minima standalone (sin depender del agente/rag.cli) para que
    # `python -m leo_code.core.guardian --base <rama>` sirva en CI (guardian.yml).
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", "-r", default=".")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--base", default=None)
    ap.add_argument("--symbol", "-s", default=None, help="Preview de impacto de UN simbolo")
    args = ap.parse_args()

    if args.symbol:
        from leo_code.rag.indexer import Indexer
        from leo_code.core.boundary import link_http_edges
        idx = Indexer()
        idx.build(args.repo, verbose=False)
        caps = idx.get_capsules()
        link_http_edges(caps)
        print(Guardian(caps, args.repo).review(args.symbol).render())
        sys.exit(0)

    if not args.staged and not args.base:
        _demo()
        sys.exit(0)

    reports, summ = guard_repo(args.repo, staged=args.staged, base=args.base)
    if not reports:
        print("guardian: no changed symbols in the diff.")
        sys.exit(0)
    for r in reports:
        print(r.render())
        print()
    risk = summ["uncovered_risk"]
    print(f"guardian · {summ['changed']} changed · {summ['affected']} affected · "
          f"{risk} with NO test (risk) — deterministic, with proof, zero LLM")
    sys.exit(1 if risk else 0)
