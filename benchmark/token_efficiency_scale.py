"""Token-efficiency a ESCALA en CUALQUIER repo grande (auto-descubre símbolos).

Prueba la meta: que cualquier agente vía MCP opere un monorepo gigante (que
revienta el context window) como si fuera un archivo pequeño. Indexa el repo,
elige los N símbolos más grandes (los que más caro saldría leer enteros) y mide,
por símbolo: tokens del contexto comprimido vs (a) el archivo, (b) el repo entero.

Determinista, offline (path estructural, sin embeddings → cero varianza). Sirve de
guard CI a escala. Reproduce el resultado en Django, en un monorepo django+sympy
(1.3M LOC, 58x un context window), o en tu propio codebase.

Uso:  python benchmark/token_efficiency_scale.py <ruta_repo> [n_simbolos]
Sale !=0 si reducción media < UMBRAL o recall < 100%.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from leo_code.core.tokens import count_tokens
from leo_code.rag.classifier import classify_task, get_budget
from leo_code.rag.compressor import compress
from benchmark.token_efficiency import _select_candidates

UMBRAL_RED = 0.80  # vs archivo entero (lo que un agente sin leo leería)


def _discover_targets(caps, repo: str, n: int) -> list[tuple[str, str]]:
    """Los N símbolos function/class/method más grandes (por tamaño de cuerpo) con
    nombre único y archivo real. Son los que más tokens ahorra no leer enteros."""
    repo_abs = str(Path(repo).resolve())
    cand = [
        c for c in caps
        if c.type in ("function", "class", "method") and c.content
        and "." not in c.name and len(c.name) > 2
        and str(Path(c.file_path).resolve()).startswith(repo_abs)
    ]
    cand.sort(key=lambda c: len(c.content), reverse=True)
    seen, out = set(), []
    for c in cand:
        if c.name in seen:
            continue
        seen.add(c.name)
        rel = str(Path(c.file_path).resolve())[len(repo_abs):].lstrip("\\/").replace("\\", "/")
        out.append((c.name, rel))
        if len(out) >= n:
            break
    return out


def run(repo: str, n: int = 10):
    from leo_code.rag.indexer import Indexer

    t0 = time.time()
    idx = Indexer()
    idx.build(repo, verbose=False)
    caps = list(idx.get_capsules().values())
    print(f"\nIndexado: {len(caps):,} cápsulas en {time.time()-t0:.0f}s")

    repo_tok = 0
    for p in Path(repo).rglob("*.py"):
        try:
            repo_tok += count_tokens(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    cw = repo_tok / 200_000
    print(f"Repo entero: ~{repo_tok:,} tokens = {cw:.0f}x un context window de 200k"
          + ("  ← NO cabe en ningún modelo actual" if cw > 1 else "") + "\n")

    targets = _discover_targets(caps, repo, n)
    print(f"{'symbol':<26}{'file_tok':>9}{'leo':>7}{'red_file':>9}{'rec':>5}")
    print("-" * 58)
    reds, recalls, leo_toks = [], [], []
    for sym, f in targets:
        fpath = Path(repo) / f
        if not fpath.exists():
            continue
        ft = count_tokens(fpath.read_text(encoding="utf-8", errors="replace"))
        q = f"¿Qué hace {sym} en {f}?"
        top, allc = _select_candidates(caps, f, sym)
        ctx = compress(top, allc, budget_tokens=get_budget(q), task_type=classify_task(q), query=q)
        leo = count_tokens(ctx)
        r = 1 - leo / ft if ft else 0.0
        rec = sym in ctx
        reds.append(r); recalls.append(1.0 if rec else 0.0); leo_toks.append(leo)
        print(f"{sym:<26}{ft:>9,}{leo:>7,}{r:>8.0%}  {'Y' if rec else 'N'}")

    avg = sum(reds) / len(reds) if reds else 0.0
    arec = sum(recalls) / len(recalls) if recalls else 0.0
    avg_leo = sum(leo_toks) / len(leo_toks) if leo_toks else 0.0
    print("-" * 58)
    print(f"\nReducción media vs archivo: {avg:.1%}  (umbral {UMBRAL_RED:.0%})")
    if repo_tok:
        print(f"Contexto medio {avg_leo:.0f} tok vs repo {repo_tok:,} tok = "
              f"{(1 - avg_leo/repo_tok)*100:.4f}% menos (el agente sin leo no puede ni cargarlo)")
    print(f"Recall símbolo: {arec:.0%}")
    return avg, arec


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    avg, rec = run(repo, n)
    sys.exit(0 if (avg >= UMBRAL_RED and rec >= 1.0) else 1)
