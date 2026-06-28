"""OrgGraph — un solo grafo determinista que une N repos y varios lenguajes.

Indexa cada repo (Python vía ast, JS/TS vía tree-sitter), fusiona todas las cápsulas
en un único store etiquetado por repo, y cose el límite HTTP (boundary) para que las
aristas crucen repos y lenguajes. El resultado se consulta con GraphQuery: where /
who_calls / callees / impact / trace, con prueba citable y cero LLM.

Es el "cerebro del código de toda la organización": el grafo del frontend, los
microservicios y la DB, unificado y consultable.

Uso CLI:  python -m leo_code.core.orggraph <repo1> <repo2> ...
"""

from __future__ import annotations

import time
from pathlib import Path

from leo_code.core.boundary import link_http_edges
from leo_code.core.graphquery import GraphQuery

_PY = ["python", "text"]
_TSJS = ((".ts", "typescript"), (".tsx", "typescript"),
         (".js", "javascript"), (".jsx", "javascript"))
_SKIP = ("node_modules", "/dist/", "/build/", "/vendor/", "/.git/", ".min.", "/out/")


def _extract_ts_js(repo: str) -> list:
    """Cápsulas de los archivos JS/TS del repo vía extract_from_file (tree-sitter).
    Bypassa el path roto del indexer y salta bundles/vendored. Resuelve el grafo de
    llamadas dentro del lote."""
    from leo_code.core.parser import extract_from_file, build_call_graph

    out = []
    for ext, lang in _TSJS:
        for p in Path(repo).rglob(f"*{ext}"):
            s = str(p).replace("\\", "/").lower()
            if any(k in s for k in _SKIP):
                continue
            try:
                out.extend(extract_from_file(str(p), lang))
            except Exception:
                pass
    build_call_graph(out)
    return out


def build_org_graph(repo_paths: list[str], verbose: bool = False) -> tuple[dict, dict]:
    """Construye el grafo unificado de varios repos y lenguajes. Devuelve (capsules, stats)."""
    from leo_code.rag.indexer import Indexer

    capsules: dict = {}
    per_repo: dict[str, int] = {}
    langs: set[str] = set()
    t0 = time.time()
    for rp in repo_paths:
        rp = str(Path(rp).resolve())
        name = Path(rp).name
        before = len(capsules)
        # Python vía ast (fiable, en su propio Indexer) + JS/TS vía tree-sitter.
        sub = Indexer()
        sub.build(rp, languages=_PY, use_tree_sitter=False, verbose=verbose)
        py_caps = list(sub.get_capsules().values())
        for c in py_caps + _extract_ts_js(rp):
            c.properties.setdefault("repo", name)
            capsules[c.id] = c
            langs.add(c.language)
        per_repo[name] = len(capsules) - before

    xlang = link_http_edges(capsules)  # aristas cross-lenguaje (HTTP)
    stats = {
        "repos": per_repo,
        "capsules": len(capsules),
        "languages": sorted(langs),
        "xlang_http_edges": xlang,
        "build_seconds": round(time.time() - t0),
    }
    return capsules, stats


def _demo():
    """Self-check sin red: dos 'repos' sintéticos (frontend TS + backend PY) unidos."""
    from leo_code.core.parser import Capsule
    from leo_code.core.boundary import link_http_edges

    def cap(name, content, file, repo, t="function", calls=None, lang="python"):
        c = Capsule(id=f"{repo}:{name}", type=t, name=name, file_path=file, start_line=1,
                    end_line=9, language=lang, signature="", content=content, calls=calls or [])
        c.properties["repo"] = repo
        return c

    caps = {c.id: c for c in [
        cap("Dashboard", "fetch('/api/report')", "web/app.tsx", "frontend", "component", lang="tsx"),
        cap("get_report", "@router.get('/api/report')\ndef get_report(): return build_report()",
            "svc/api.py", "backend", "endpoint", calls=["build_report"]),
        cap("build_report", "def build_report(): return read_metrics()", "svc/logic.py", "backend",
            calls=["read_metrics"]),
        cap("read_metrics", "def read_metrics(): pass", "svc/db.py", "backend", t="model"),
    ]}
    n = link_http_edges(caps)
    assert n == 1, n
    g = GraphQuery(caps)
    tr = g.trace("Dashboard", "read_metrics")
    repos = [c.repo for c in tr.cites]
    assert repos[0] == "frontend" and "backend" in repos, repos  # cruza repos
    print("orggraph self-check OK — trace cross-repo + cross-lenguaje")
    print(tr.render())


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        caps, stats = build_org_graph(sys.argv[1:], verbose=False)
        print("STATS:", stats)
    else:
        _demo()
