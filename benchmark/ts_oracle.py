"""Oráculo TS — verifica que el grafo de llamadas TS/JS de leo es SOUND y COMPLETE
contra el COMPILADOR TypeScript (parser independiente del tree-sitter de leo).

Corre `node benchmark/ts_oracle.js <repo>` para re-derivar las aristas con tsc, indexa el
mismo repo con leo (languages ts/js), empareja símbolos por (archivo, nombre, línea) y mide:

  precisión = aristas de leo que existen en tsc   (aristas FALSAS)
  recall    = aristas de tsc que leo encontró     (aristas PERDIDAS)

Requiere node + el paquete `typescript` accesible por node. Si faltan, es un fallo de
setup (no un pase): retorna (0,0,0). Uso:  python benchmark/ts_oracle.py <repo_ts>
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
ROOT = Path(__file__).parent.parent
_JS = ROOT / "benchmark" / "ts_oracle.js"


def _oracle(repo: str) -> dict:
    """{(archivo_abs, nombre_base, línea): set(calls)} re-derivado por tsc."""
    out = subprocess.run(["node", str(_JS), repo], capture_output=True, text=True,
                         timeout=900, encoding="utf-8", errors="replace")
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"node/tsc falló: {out.stderr[:200]}")
    data = json.loads(out.stdout)
    omap = {}
    for f, syms in data.items():
        rf = str(Path(f).resolve())
        for name, line, calls in syms:
            omap[(rf, str(name).split(".")[-1], line)] = set(calls)
    return omap


def run(repo: str = "."):
    try:
        omap = _oracle(repo)
    except Exception as e:
        print(f"❌ ORÁCULO TS NO EJECUTABLE en {repo!r}: {e} (node + npm i typescript)")
        return 0.0, 0.0, 0

    from leo_code.rag.indexer import Indexer
    idx = Indexer()
    idx.build(repo, languages=["typescript", "javascript"], verbose=False)

    code_types = {"function", "method", "class", "async_function"}
    tot_leo = tot_or = tot_int = 0
    matched = 0
    false_e, miss_e = [], []
    for c in idx.get_capsules().values():
        if c.type not in code_types or not (c.file_path or "").endswith((".ts", ".tsx")):
            continue
        key = (str(Path(c.file_path).resolve()), c.name.split(".")[-1], c.start_line)
        if key not in omap:
            continue   # símbolo no comparable (arrow/.d.ts/desalineado) → fuera de alcance
        matched += 1
        leo, orc = set(c.calls or []), omap[key]
        tot_leo += len(leo); tot_or += len(orc); tot_int += len(leo & orc)
        for e in leo - orc:
            false_e.append((c.name, c.start_line, e))
        for e in orc - leo:
            miss_e.append((c.name, c.start_line, e))

    if matched == 0 or tot_or == 0:
        print(f"❌ ORÁCULO TS VACUO en {repo!r}: 0 símbolos comparables (no es un pase).")
        return 0.0, 0.0, 0

    precision = tot_int / tot_leo if tot_leo else 1.0
    recall = tot_int / tot_or if tot_or else 1.0
    print(f"TS símbolos comparados: {matched:,}  ·  aristas leo: {tot_leo:,}  ·  tsc: {tot_or:,}")
    print(f"PRECISIÓN (sin falsas):   {precision*100:.3f}%  ({len(false_e)} falsas)")
    print(f"RECALL    (sin perdidas): {recall*100:.3f}%  ({len(miss_e)} perdidas)")
    for n, ln, e in (false_e + miss_e)[:12]:
        print(f"    disputa {n}:{ln} → {e}")
    return precision, recall, matched


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    p, r, n = run(repo)
    sys.exit(0 if (n > 0 and p >= 0.999 and r >= 0.999) else 1)
