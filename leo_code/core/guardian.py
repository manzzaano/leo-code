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

from collections import deque
from dataclasses import dataclass, field

from leo_code.core.graphquery import GraphQuery, Cite, _bare


@dataclass
class Affected:
    """Un símbolo dentro del radio de explosión, con su estado de cobertura."""
    cite: Cite
    covered: bool          # ¿lo alcanza algún test?

    def __str__(self) -> str:
        mark = "✓ test" if self.covered else "✗ SIN test"
        return f"{self.cite}  [{mark}]"


@dataclass
class ChangeReport:
    """Resultado de revisar UN símbolo cambiado."""
    symbol: str
    changed_covered: bool
    affected: list[Affected] = field(default_factory=list)

    @property
    def uncovered(self) -> list[Affected]:
        return [a for a in self.affected if not a.covered]

    def render(self) -> str:
        lines = [f"cambias `{self.symbol}`"
                 + ("  [✓ con test]" if self.changed_covered else "  [✗ SIN test]")]
        if not self.affected:
            lines.append("  → no rompe a nadie indexado.")
            return "\n".join(lines)
        risk = len(self.uncovered)
        lines.append(f"  → afecta a {len(self.affected)} símbolo(s)"
                     + (f", {risk} SIN test (riesgo)" if risk else ", todos con test ✓"))
        for a in self.affected[:40]:
            lines.append(f"    · {a}")
        return "\n".join(lines)


class Guardian:
    def __init__(self, capsules: dict):
        # El guardián usa el grafo AUMENTADO con aristas de referencia/dispatch
        # (completitud: cambiar X que se invoca por dict debe marcar a quien lo despacha).
        # Sobre una COPIA de las listas `calls` para NO contaminar el grafo directo y
        # preciso que usan who_calls/trace/where (que se demuestra sound+complete vs ast).
        import copy
        from leo_code.core.refgraph import augment_refs
        aug = {}
        for k, c in (capsules or {}).items():
            cc = copy.copy(c)
            cc.calls = list(c.calls or [])
            aug[k] = cc
        augment_refs(aug)
        self.caps = aug
        self.gq = GraphQuery(aug)
        self._covered: set[str] | None = None

    # ---- cobertura: símbolos alcanzados por algún test ----
    @staticmethod
    def _is_test(c) -> bool:
        if c.type == "test":
            return True
        nm = (c.name or "").lower()
        fp = (c.file_path or "").lower().replace("\\", "/")
        return nm.startswith("test_") or "/tests/" in fp or fp.endswith("_test.py") \
            or "test" in fp.split("/")[-1]

    def test_closure(self) -> set[str]:
        """Nombres (base) alcanzables desde cualquier test siguiendo `calls` (transitivo)."""
        if self._covered is not None:
            return self._covered
        by_name: dict[str, list] = {}
        for c in self.caps.values():
            by_name.setdefault(_bare(c.name), []).append(c)
        seen: set[str] = set()
        q: deque = deque()
        for c in self.caps.values():
            if self._is_test(c):
                for callee in (c.calls or []):
                    q.append(_bare(callee))
        while q:
            name = q.popleft()
            if name in seen:
                continue
            seen.add(name)
            for c in by_name.get(name, []):
                for callee in (c.calls or []):
                    b = _bare(callee)
                    if b not in seen:
                        q.append(b)
        self._covered = seen
        return seen

    def is_covered(self, name: str) -> bool:
        return _bare(name) in self.test_closure()

    # ---- radio de explosión + revisión ----
    def review(self, changed_symbol: str, limit: int = 200) -> ChangeReport:
        impact = self.gq.impact(changed_symbol, limit=limit)
        affected = [Affected(c, self.is_covered(c.name)) for c in impact.cites]
        return ChangeReport(symbol=changed_symbol,
                            changed_covered=self.is_covered(changed_symbol),
                            affected=affected)

    def review_many(self, symbols: list[str]) -> list[ChangeReport]:
        return [self.review(s) for s in symbols]

    # ---- diff de git → símbolos cambiados → revisión (PR/CI guardian) ----
    def changed_symbols(self, diff_text: str) -> list[str]:
        """Mapea las líneas cambiadas de un `git diff` a los símbolos (cápsulas) que
        las contienen. Es el puente diff → grafo."""
        import re
        import os
        changes: dict[str, set[int]] = {}   # archivo → líneas (lado nuevo) tocadas
        cur = None
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:].strip()
                changes.setdefault(cur, set())
            elif line.startswith("@@") and cur is not None:
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if m:
                    start = int(m.group(1)); count = int(m.group(2) or 1)
                    changes[cur].update(range(start, start + max(count, 1)))
        # cápsulas cuyo rango [start,end] solapa con líneas cambiadas del mismo archivo
        out: list[str] = []
        seen: set[str] = set()
        for c in self.caps.values():
            cf = (c.file_path or "").replace("\\", "/")
            for f, lines in changes.items():
                if cf.endswith(f) or os.path.basename(cf) == os.path.basename(f):
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
    g = Guardian(caps)
    reports = g.review_diff(git_diff(repo, staged, base))
    affected = sum(len(r.affected) for r in reports)
    uncovered = sum(len(r.uncovered) for r in reports)
    summary = {"changed": len(reports), "affected": affected, "uncovered_risk": uncovered}
    return reports, summary


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
    _demo()
