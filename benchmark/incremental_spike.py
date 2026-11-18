"""Espiga de la unidad 2 (plan 2026-11-18-reconstruccion-incremental): ¿cuántas cápsulas
hay que volver a resolver cuando se edita un archivo?

Para cada archivo llamante H anota qué archivos consultó `_PyScope.resolve` al resolver sus
llamadas: los módulos que importa (y sus re-exports), la MRO de las clases que despacha y
sus subclases. Es una cota superior: ante la duda anota de más, nunca de menos.

Editar E sin cambiar su estructura (mismas defs, imports y clases) obliga a re-resolver los
llamantes que consultaron E. Lo que cambia la estructura (añadir un archivo, una subclase, un
import) también toca tablas globales (`mods`, `subs`): eso se mide aparte, contando cuántos
llamantes dependen de cada clase por sus subclases.

Uso: python benchmark/incremental_spike.py <repo>
"""

import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code import engine                                   # noqa: E402
from leo_code.core.graphquery import _PyScope, _norm          # noqa: E402
from leo_code.rag.indexer import Indexer                      # noqa: E402


def _file(key: str) -> str:
    return key.split("\0", 1)[0]


class _Rec(_PyScope):
    """_PyScope que anota en `cur` los archivos que consulta."""

    # al construir, _class_keys ya consulta otros archivos (bases): eso es la jerarquía,
    # que se mide aparte; aquí se descarta
    cur: set = set()
    cur_classes: set = set()      # clases sobre las que despacha el archivo en curso

    def _mod_files(self, mod, level, here):
        out = super()._mod_files(mod, level, here)
        if out:
            self.cur.update(out)
        return out

    def _in_module(self, files, attr, depth):
        self.cur.update(files)
        return super()._in_module(files, attr, depth)

    def _mro(self, k):
        out = super()._mro(k)
        self.cur.update(_file(x) for x in out if x[0] != "\0")
        return out

    def _dispatch(self, k, name, sup):
        for sub in self._desc(k):
            self.cur.add(_file(sub))
            self.cur.update(_file(x) for x in self._mro(sub) if x[0] != "\0")
        self.cur_classes.add(k)
        return super()._dispatch(k, name, sup)


def main(repo: str) -> None:
    repo = os.path.abspath(repo)
    idx = Indexer()
    idx.build(repo, languages=["python", "typescript", "javascript"], verbose=False)
    caps = list(engine._repo_caps(idx, repo))
    scope = _Rec(caps)

    by_file = defaultdict(list)
    for c in caps:
        by_file[_norm(c.file_path)].append(c)
    deps: dict[str, set] = {}
    on_class: dict[str, set] = defaultdict(set)     # clase → archivos que despachan sobre ella
    t0 = time.perf_counter()
    for f, cs in by_file.items():
        scope.cur, scope.cur_classes = {f}, set()
        for c in cs:
            forms = (c.properties or {}).get("call_forms")
            if forms:
                scope.resolve(c, forms, [], {})
        deps[f] = scope.cur
        for k in scope.cur_classes:
            on_class[k].add(f)
    took = time.perf_counter() - t0
    # el memo por archivo de resolve se comparte entre llamantes del mismo archivo: correcto,
    # porque la granularidad es el archivo (sync sustituye archivos enteros)

    users = defaultdict(set)            # E → archivos llamantes que consultaron E
    for h, ds in deps.items():
        for e in ds:
            users[e].add(h)
    n_caps = len(caps)
    size = {f: len(cs) for f, cs in by_file.items()}

    def frac(files) -> float:
        return sum(size.get(h, 0) for h in files) / n_caps

    py = [f for f in by_file if f.endswith(".py")]
    fr = sorted(frac(users.get(e, {e})) for e in py)
    # edición ponderada por símbolos: se edita más donde hay más código
    w = sum(size[e] for e in py)
    weighted = sum(size[e] * frac(users.get(e, {e})) for e in py) / w

    def pct(q):
        return fr[min(len(fr) - 1, int(q * len(fr)))]

    print(f"{Path(repo).name}: {n_caps:,} cápsulas · {len(py):,} archivos .py · "
          f"anotar dependencias {took:.1f} s")
    print("cápsulas a re-resolver al editar 1 archivo sin cambiar su estructura (% del repo):")
    print(f"  mediana {pct(.5):.2%} · p90 {pct(.9):.2%} · p99 {pct(.99):.2%} · "
          f"máx {fr[-1]:.2%} · media {statistics.fmean(fr):.2%} · "
          f"media ponderada por símbolos {weighted:.2%}")
    top = sorted(py, key=lambda e: -frac(users.get(e, {e})))[:8]
    print("  archivos más consultados:")
    for e in top:
        print(f"    {frac(users.get(e, {e})):6.2%}  {len(users.get(e, ())):5} llamantes  "
              f"{os.path.relpath(e, _norm(repo)) if e.startswith(_norm(repo)) else e}")
    # cambio de jerarquía en la clase K (añadir o quitar una subclase, cambiar bases):
    # re-resolver lo que despacha sobre K o sobre sus ancestros
    hier = []
    for k in scope.classes:
        files = set()
        for a in scope._mro(k):
            files |= on_class.get(a, set())
        hier.append(frac(files))
    hier.sort()
    print("cambio de jerarquía en 1 clase (% del repo a re-resolver):")
    print(f"  mediana {hier[len(hier) // 2]:.2%} · p90 {hier[int(.9 * len(hier))]:.2%} · "
          f"máx {hier[-1]:.2%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
