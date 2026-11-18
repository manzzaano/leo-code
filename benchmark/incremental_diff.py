"""Diferencial de GraphQuery.update a escala (plan 2026-11-18, unidad 3, criterios 2 y 3).

Edita al azar archivos .py de un clon git (cuerpo, defs nuevas, imports, clases), re-sincroniza
el índice y compara `update` con `GraphQuery` construido desde cero: índices iguales, orden de
las listas incluido. Mide también cuánto cuesta cada camino. Restaura el clon al acabar
(`git checkout`/`git clean`): no usar sobre un repo con cambios sin guardar.

Uso: python benchmark/incremental_diff.py <clon git> [ediciones=200] [semilla=18]
"""

import gc
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code import engine                                   # noqa: E402
from leo_code.core.boundary import link_http_edges            # noqa: E402
from leo_code.core.graphquery import GraphQuery               # noqa: E402
from leo_code.rag.indexer import Indexer                      # noqa: E402


def snap(gq):
    ids = lambda d: {k: [c.id for c in v] for k, v in d.items()}
    return (ids(gq.by_name), ids(gq.callers), ids(gq._res), dict(gq._qref),
            {k: set(v) for k, v in gq._fams.items()})


def _edit(rnd, text: str, i: int) -> str:
    kind = rnd.choice(["cuerpo", "cuerpo", "cuerpo", "def", "import", "clase", "linea"])
    if kind == "cuerpo":            # una llamada más dentro de una def que ya existe
        lines = text.splitlines(keepends=True)
        defs = [j for j, ln in enumerate(lines) if ln.lstrip().startswith("def ") and ln.rstrip().endswith(":")]
        if defs:
            j = rnd.choice(defs)
            ind = " " * (len(lines[j]) - len(lines[j].lstrip()) + 4)
            lines.insert(j + 1, f"{ind}_ = {rnd.choice(['len', 'self.save', 'force_str', 'get_user_model', 'run'])}()\n")
            return "".join(lines)
    if kind == "import":
        return f"from django.utils.encoding import force_str as _leo{i}\n" + text
    if kind == "clase":
        return text + f"\n\nclass _Leo{i}(object):\n    def save(self):\n        return self.clean()\n"
    if kind == "linea":             # desplaza las líneas: ids nuevos para todo el archivo
        return "# leo\n" + text
    return text + f"\n\ndef _leo_{i}():\n    return force_str(1)\n"


def main(repo: str, n: int, seed: int) -> int:
    repo = os.path.abspath(repo)
    rnd = random.Random(seed)
    idx = Indexer()
    idx.build(repo, languages=["python", "typescript", "javascript"], verbose=False)
    caps = {c.id: c for c in engine._repo_caps(idx, repo)}
    link_http_edges(caps)
    gq = GraphQuery(caps)
    files = sorted({c.file_path for c in caps.values() if c.file_path.endswith(".py")})
    t_inc, t_full, t_cold, bad = [], [], [], 0
    try:
        for i in range(n):
            f = rnd.choice(files)
            p = Path(f)
            p.write_text(_edit(rnd, p.read_text(encoding="utf-8"), i), encoding="utf-8")
            idx.sync(repo, since_mtime=float("inf"), paths={f})
            caps = {c.id: c for c in engine._repo_caps(idx, repo)}
            gc.collect()
            t0 = time.perf_counter()
            touched: set = set()
            link_http_edges(caps, touched)
            inc = gq.update(caps, touched)
            dt = time.perf_counter() - t0
            (t_inc if inc else t_full).append(dt)
            gc.collect()
            t0 = time.perf_counter()
            cold = GraphQuery(caps)
            t_cold.append(time.perf_counter() - t0)
            if snap(gq) != snap(cold):
                bad += 1
                print(f"  ❌ edición {i} en {os.path.relpath(f, repo)} ({'incremental' if inc else 'entera'})")
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{n} · distintas {bad}", flush=True)
    finally:
        subprocess.run(["git", "-C", repo, "checkout", "--", "."], check=False)
        subprocess.run(["git", "-C", repo, "clean", "-fdq"], check=False)
    ms = lambda xs: f"mediana {statistics.median(xs) * 1e3:.0f} ms" if xs else "—"
    print(f"{Path(repo).name}: {n} ediciones · {len(caps):,} cápsulas · distintas de cero: {bad}")
    print(f"  incrementales {len(t_inc)}: {ms(t_inc)}"
          + (f", p90 {sorted(t_inc)[int(.9 * len(t_inc))] * 1e3:.0f} ms" if t_inc else ""))
    print(f"  enteras {len(t_full)}: {ms(t_full)} · GraphQuery desde cero: {ms(t_cold)}")
    if t_inc:
        print(f"  incremental / desde cero: {statistics.median(t_inc) / statistics.median(t_cold):.2f}")
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], int(a[1]) if len(a) > 1 else 200, int(a[2]) if len(a) > 2 else 18))
