"""Oráculo (f) de RESOLUCIÓN — ¿a qué definición va cada llamada?

El oráculo (a) compara nombres de llamada (`save`) y no puede ver si leo une la llamada
con la definición correcta cuando hay homónimos. Este compara aristas
caller→definición contra el micro-benchmark de PyCG (Salis et al., ICSE 2021): 119
programas mínimos con su grafo de llamadas hecho a mano (`callgraph.json`).

Solo puntúa aristas cuyos dos extremos son definiciones que leo indexa: mide la
resolución, no la extracción. Aparte se cuentan las llamadas desde el nivel de módulo
(leo no tiene cápsula de módulo que haga de caller) y las que tocan definiciones que
leo no indexa (lambdas, funciones anidadas).

Nomenclatura de PyCG: complete = sin aristas falsas, sound = sin aristas perdidas.

A escala no hay grafo hecho a mano: el juez es jedi (`goto` siguiendo imports), y se
puntúa por sitio de llamada (caller, línea:columna, destino).

Uso:  python benchmark/resolution_oracle.py <PyCG>/micro-benchmark/snippets
      python benchmark/resolution_oracle.py --repo <ruta> [--sample N]
"""

import ast
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python


def _module(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _qname(c, root: Path) -> str:
    return f"{_module(Path(c.file_path), root)}.{(c.properties or {}).get('qualified') or c.name}"


def leo_edges(root: Path) -> tuple[set, set]:
    """(aristas caller→def que daría leo hoy, nombres cualificados de sus defs)."""
    caps = {}
    for py in sorted(root.rglob("*.py")):
        for c in extract_from_python(py.read_text(encoding="utf-8", errors="replace"), str(py)):
            caps[c.id] = c
    gq = GraphQuery(caps)
    # Las clases quedan fuera: PyCG modela `C()` como llamada a `C.__init__`, y decidir
    # qué `__init__` toca (MRO) ya es resolución que leo no hace.
    defs = [c for c in caps.values() if gq._is_def(c) and c.type != "class"]
    known = {_qname(c, root) for c in defs}
    edges = set()
    for d in defs:
        for caller in gq._callers_of(d.name):
            if gq._is_def(caller) and caller.type != "class":
                edges.add((_qname(caller, root), _qname(d, root)))
    return edges, known


def score_snippet(test_dir: Path) -> dict:
    truth_raw = json.loads((test_dir / "callgraph.json").read_text(encoding="utf-8"))
    leo, known = leo_edges(test_dir)
    modules = {_module(p, test_dir) for p in test_dir.rglob("*.py")}
    truth, module_level, unindexed = set(), 0, 0
    for caller, callees in truth_raw.items():
        for callee in callees:
            if callee.split(".")[0] not in modules:
                continue                     # builtins y librerías externas
            if caller in modules:
                module_level += 1
            elif caller in known and callee in known:
                truth.add((caller, callee))
            else:
                unindexed += 1
    leo = {e for e in leo if e[0] in known and e[1] in known}
    return {"truth": truth, "leo": leo, "complete": not (leo - truth), "sound": not (truth - leo),
            "module_level": module_level, "unindexed": unindexed}


def _site(f) -> tuple[int, int]:
    """Posición del nombre llamado: `foo` en `foo()` y `attr` en `obj.attr()`."""
    if isinstance(f, ast.Attribute):
        return f.end_lineno, f.end_col_offset - len(f.attr)
    return f.lineno, f.col_offset


def score_repo(repo: str, sample: int | None = None, seed: int = 0) -> dict:
    """Juez a escala: jedi (`goto` siguiendo imports) dice a qué def va cada llamada.

    Solo se puntúan las llamadas que jedi resuelve a una def que leo indexa; el resto
    (librerías, builtins, lo que jedi no sabe) se cuenta como `unjudged`."""
    import jedi
    from leo_code.rag.indexer import Indexer
    from leo_code.core.graphquery import _bare
    from leo_code.core.parser import call_form

    root = Path(repo).resolve()
    idx = Indexer()
    idx.build(str(root), verbose=False)
    caps = idx.get_capsules()
    gq = GraphQuery(caps)
    defs = {}
    for c in caps.values():
        if gq._is_def(c) and c.type != "class" and (c.file_path or "").endswith(".py"):
            defs[(Path(c.file_path).resolve(), c.start_line)] = c
    by_bare = defaultdict(list)
    for c in defs.values():
        by_bare[_bare(c.name)].append(c)

    def qid(c) -> str:
        rel = Path(c.file_path).resolve().relative_to(root).as_posix()
        return f"{rel}:{(c.properties or {}).get('qualified') or c.name}"

    sites = []                         # (caller, archivo, línea, columna, nombre)
    trees = {}
    for (path, line), c in defs.items():
        if path not in trees:
            trees[path] = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        node = next((n for n in ast.walk(trees[path])
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno == line), None)
        if node is None:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute)):
                sites.append((c, path, *_site(call.func), *call_form(call.func)))
    if sample and len(sites) > sample:
        # el índice no garantiza orden: sin ordenar, la misma semilla daba otra muestra
        sites.sort(key=lambda s: (str(s[1]), s[2], s[3]))
        sites = random.Random(seed).sample(sites, sample)

    project = jedi.Project(str(root))
    scripts = {}
    truth, leo = set(), set()
    calls = exact = unjudged = linked = 0
    for caller, path, line, col, name, recv in sites:
        if path not in scripts:
            scripts[path] = jedi.Script(path=str(path), project=project)
        try:
            found = scripts[path].goto(line, col, follow_imports=True)
        except Exception:              # jedi falla en código raro: no hay veredicto
            found = []
        targets = {qid(defs[(Path(d.module_path).resolve(), d.line)])
                   for d in found if d.type == "function" and d.module_path
                   and (Path(d.module_path).resolve(), d.line) in defs}
        if not targets:
            unjudged += 1
            linked += name in by_bare     # leo la une por nombre y nadie puede juzgarla
            continue
        site = f"{line}:{col}"
        resolved = gq._scope.targets(caller, name, recv)
        if resolved is None:           # sin resolver: leo la une por nombre
            guessed = {qid(d) for d in by_bare.get(name, []) if gq._edge_ok(caller, name)}
        else:
            guessed = {qid(d) for d in resolved if (Path(d.file_path).resolve(), d.start_line) in defs}
        calls += 1
        exact += guessed == targets
        truth |= {(qid(caller), site, t) for t in targets}
        leo |= {(qid(caller), site, g) for g in guessed}
    return {"truth": truth, "leo": leo, "calls": calls, "exact": exact,
            "unjudged": unjudged, "linked_unjudged": linked, "sites": len(sites)}


def run(snippets: str) -> tuple[float, float, int]:
    root = Path(snippets)
    by_cat = defaultdict(lambda: {"n": 0, "complete": 0, "sound": 0})
    tp = n_leo = n_truth = module_level = unindexed = 0
    false_edges = []
    for cg in sorted(root.rglob("callgraph.json")):
        s = score_snippet(cg.parent)
        cat = by_cat[cg.parent.parent.name]
        cat["n"] += 1; cat["complete"] += s["complete"]; cat["sound"] += s["sound"]
        tp += len(s["leo"] & s["truth"]); n_leo += len(s["leo"]); n_truth += len(s["truth"])
        module_level += s["module_level"]; unindexed += s["unindexed"]
        false_edges += [(cg.parent.relative_to(root).as_posix(), e) for e in s["leo"] - s["truth"]]

    if n_truth == 0:
        print(f"❌ ORÁCULO VACUO: 0 aristas puntuables en {snippets!r} (ruta mala).")
        return 0.0, 0.0, 0

    precision = tp / n_leo if n_leo else 1.0
    recall = tp / n_truth
    print(f"{'categoría':<14}{'tests':>6}{'complete':>10}{'sound':>8}")
    for name, c in sorted(by_cat.items()):
        print(f"{name:<14}{c['n']:>6}{c['complete']:>10}{c['sound']:>8}")
    tests = sum(c["n"] for c in by_cat.values())
    print(f"{'TOTAL':<14}{tests:>6}{sum(c['complete'] for c in by_cat.values()):>10}"
          f"{sum(c['sound'] for c in by_cat.values()):>8}")
    print(f"aristas puntuadas: verdad {n_truth} · leo {n_leo} · acertadas {tp}")
    print(f"PRECISIÓN de resolución: {precision*100:.1f}%  ({n_leo - tp} falsas)")
    print(f"RECALL de resolución:    {recall*100:.1f}%  ({n_truth - tp} perdidas)")
    print(f"fuera de la puntuación: {module_level} desde nivel de módulo · "
          f"{unindexed} con un extremo que leo no indexa")
    for where, (a, b) in false_edges[:12]:
        print(f"  falsa  {where}: {a} → {b}")
    return precision, recall, tests


def run_repo(repo: str, sample: int | None) -> tuple[float, float, float]:
    t0 = time.perf_counter()
    s = score_repo(repo, sample)
    if s["calls"] == 0:
        print(f"❌ ORÁCULO VACUO: jedi no resolvió ninguna llamada interna en {repo!r}.")
        return 0.0, 0.0, 0.0
    tp = len(s["leo"] & s["truth"])
    precision = tp / len(s["leo"]) if s["leo"] else 1.0
    recall = tp / len(s["truth"])
    exact = s["exact"] / s["calls"]
    print(f"{Path(repo).resolve().name}: {s['sites']} llamadas examinadas · {s['calls']} juzgadas por jedi · "
          f"{s['unjudged']} sin veredicto · {time.perf_counter() - t0:.0f} s")
    print(f"  de las sin veredicto, {s['linked_unjudged']} las une leo por nombre (sin juzgar)")
    print(f"PRECISIÓN de resolución: {precision*100:.1f}%  ({len(s['leo']) - tp} destinos falsos)")
    print(f"RECALL de resolución:    {recall*100:.1f}%  ({len(s['truth']) - tp} destinos perdidos)")
    print(f"EXACTAS (leo da justo el destino correcto): {exact*100:.1f}%")
    return precision, recall, exact


if __name__ == "__main__":
    from leo_code.logging_config import utf8_console
    utf8_console()
    if len(sys.argv) >= 3 and sys.argv[1] == "--repo":
        n = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else None
        run_repo(sys.argv[2], n)
    elif len(sys.argv) == 2:
        run(sys.argv[1])
    else:
        sys.exit(__doc__)
