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


def _oracle(repo: str) -> tuple[dict, set]:
    """({(archivo_abs, nombre_base, línea): set(calls)}, archivos que tsc leyó sin error)."""
    out = subprocess.run(["node", str(_JS), repo], capture_output=True, text=True,
                         timeout=900, encoding="utf-8", errors="replace")
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"node/tsc falló: {out.stderr[:200]}")
    data = json.loads(out.stdout)
    omap = {}
    for f, syms in data.items():
        rf = str(Path(f).resolve())
        for name, line, calls in syms:
            # get y set del mismo nombre en la misma línea comparten clave: se unen
            omap.setdefault((rf, str(name).split(".")[-1], line), set()).update(calls)
    return omap, {str(Path(f).resolve()) for f in data}


def run(repo: str = "."):
    try:
        omap, tsc_files = _oracle(repo)
    except Exception as e:
        print(f"❌ ORÁCULO TS NO EJECUTABLE en {repo!r}: {e} (node + npm i typescript)")
        return 0.0, 0.0, 0

    from leo_code.rag.indexer import Indexer
    idx = Indexer()
    idx.build(repo, languages=["typescript", "javascript"], verbose=False)

    code_types = {"function", "method", "class", "async_function", "type_def", "component"}
    # Símbolos: las aristas solo se comparan en los que leo ya tiene, y así un hueco del
    # parser no se veía (#9). Por clave completa (archivo, nombre, línea) y en los dos
    # sentidos: un símbolo en otra línea es uno perdido y uno de más.
    leo_syms = {(str(Path(c.file_path).resolve()), c.name.split(".")[-1], c.start_line)
                for c in idx.get_capsules().values()}
    seen_files = {k[0] for k in leo_syms}                 # lo que leo excluye a propósito no cuenta
    # Sintaxis que tsc solo rechaza en el checker (`y?: T = 1`) y tree-sitter no sabe leer:
    # cada parser se recupera a su manera, igual que con los parseDiagnostics de ts_oracle.js.
    # Coste aceptado: también salta sintaxis válida que tree-sitter aún no conoce; se imprime.
    from leo_code.core.parser_ts import _parser
    broken = {f for f in tsc_files & seen_files
              if _parser("tsx" if f.endswith("x") else "typescript")
              .parse(Path(f).read_bytes()).root_node.has_error}
    wanted = {k for k in omap if k[0] in seen_files and k[0] not in broken}
    ok_files = (tsc_files & seen_files) - broken
    extra = sorted(k for k in leo_syms if k[0] in ok_files and k not in omap)
    lost = sorted(wanted - leo_syms)
    tot_leo = tot_or = tot_int = 0
    matched = 0
    false_e, miss_e = [], []
    leo_map: dict = {}   # misma unión por clave que omap
    for c in idx.get_capsules().values():
        if c.type not in code_types or not (c.file_path or "").endswith((".ts", ".tsx")):
            continue
        key = (str(Path(c.file_path).resolve()), c.name.split(".")[-1], c.start_line)
        if key not in omap or key[0] in broken:
            continue   # símbolo no comparable (arrow/.d.ts/desalineado) → fuera de alcance
        leo_map.setdefault(key, set()).update(c.calls or [])
    for key, leo in leo_map.items():
        matched += 1
        orc = omap[key]
        tot_leo += len(leo); tot_or += len(orc); tot_int += len(leo & orc)
        for e in leo - orc:
            false_e.append((key[1], key[2], e))
        for e in orc - leo:
            miss_e.append((key[1], key[2], e))

    if matched == 0 or tot_or == 0:
        print(f"❌ ORÁCULO TS VACUO en {repo!r}: 0 símbolos comparables (no es un pase).")
        return 0.0, 0.0, 0

    precision = tot_int / tot_leo if tot_leo else 1.0
    recall = tot_int / tot_or if tot_or else 1.0
    sym_recall = 1 - len(lost) / len(wanted)
    sym_prec = 1 - len(extra) / max(1, len({k for k in leo_syms if k[0] in ok_files}))
    print(f"TS símbolos comparados: {matched:,}  ·  aristas leo: {tot_leo:,}  ·  tsc: {tot_or:,}")
    print(f"Archivos saltados por sintaxis que tree-sitter no lee: {len(broken)}")
    print(f"SÍMBOLOS perdidos: {len(lost)} ({sym_recall*100:.3f}%)", [f"{Path(f).name}:{ln}:{n}" for f, n, ln in lost[:12]])
    print(f"SÍMBOLOS de más:   {len(extra)} ({sym_prec*100:.3f}%)", [f"{Path(f).name}:{ln}:{n}" for f, n, ln in extra[:12]])
    print(f"PRECISIÓN (sin falsas):   {precision*100:.3f}%  ({len(false_e)} falsas)")
    print(f"RECALL    (sin perdidas): {recall*100:.3f}%  ({len(miss_e)} perdidas)")
    for n, ln, e in (false_e + miss_e)[:12]:
        print(f"    disputa {n}:{ln} → {e}")
    return min(precision, sym_prec), min(recall, sym_recall), matched


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    p, r, n = run(repo)
    sys.exit(0 if (n > 0 and p >= 0.999 and r >= 0.999) else 1)
