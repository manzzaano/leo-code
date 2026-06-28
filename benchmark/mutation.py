"""Mutation testing — prueba que el blast radius del guardián es COMPLETO.

Rompe un símbolo de verdad (inyecta un fallo en su cuerpo), corre la suite, y verifica
que TODOS los tests que fallan están dentro del radio de explosión que leo predijo con
`impact(símbolo)`. Si un test falla y leo NO lo anticipó → arista perdida (incompleto).
Reversible: restaura el archivo siempre (try/finally).

Uso:  python benchmark/mutation.py [símbolo ...]    (default: símbolos con tests)
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
ROOT = Path(__file__).parent.parent


def _predicted_tests(symbol: str) -> set[str]:
    """Tests dentro del radio de explosión de `symbol` según el grafo de leo."""
    from leo_code.rag.indexer import Indexer
    from leo_code.core.guardian import Guardian
    idx = Indexer(); idx.build(str(ROOT), verbose=False)
    g = Guardian(idx.get_capsules())
    rep = g.review(symbol, limit=500)
    affected = {a.cite.name for a in rep.affected}
    affected.add(symbol)
    # nombres de funciones test alcanzadas (las que pytest reportaría)
    return {n for n in affected if n.startswith("test_")}


def _locate(symbol: str) -> tuple[Path, int] | None:
    from leo_code.rag.indexer import Indexer
    idx = Indexer(); idx.build(str(ROOT), verbose=False)
    for c in idx.get_capsules().values():
        if c.name == symbol and c.type in ("function", "method", "async_function"):
            return Path(c.file_path), c.start_line
    return None


def _failing_tests(output: str) -> set[str]:
    """Nombres de funciones test que FAIL/ERROR en la salida de pytest."""
    out = set()
    for m in re.finditer(r"(?:FAILED|ERROR)\s+\S+::(\w+)", output):
        out.add(m.group(1))
    for m in re.finditer(r"^(test_\w+)\b", output, re.MULTILINE):
        out.add(m.group(1))
    return out


def mutate_one(symbol: str) -> tuple[bool, str]:
    loc = _locate(symbol)
    if not loc:
        return True, f"{symbol}: no localizable (skip)"
    path, line = loc
    predicted = _predicted_tests(symbol)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    # inyecta un fallo justo tras la firma (línea def): cuerpo indentado con raise
    idx = line - 1
    # buscar el final de la firma (línea que acaba en ':')
    while idx < len(lines) and not lines[idx].rstrip().endswith(":"):
        idx += 1
    indent = " " * (len(lines[idx]) - len(lines[idx].lstrip()) + 4)
    lines.insert(idx + 1, f'{indent}raise RuntimeError("MUTATION")\n')
    try:
        path.write_text("".join(lines), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--no-header", "-x" if False else "-p", "no:cacheprovider"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        failing = _failing_tests(r.stdout + r.stderr)
    finally:
        path.write_text(original, encoding="utf-8")   # SIEMPRE restaura
    unpredicted = failing - predicted
    ok = not unpredicted
    detail = (f"{symbol}: {len(failing)} tests fallaron, predichos {len(predicted)}; "
              + ("todos ⊆ blast radius ✓" if ok else f"NO anticipados: {sorted(unpredicted)[:6]}"))
    return ok, detail


def main(symbols: list[str]):
    print("MUTATION TESTING — ¿el blast radius anticipa toda rotura?")
    print("-" * 64)
    allok = True
    for s in symbols:
        ok, detail = mutate_one(s)
        print(("✅" if ok else "❌") + " " + detail)
        allok = allok and ok
    print("-" * 64)
    print("RESULTADO:", "completo ✅" if allok else "INCOMPLETO ❌")
    return 0 if allok else 1


if __name__ == "__main__":
    syms = sys.argv[1:] or ["compress", "classify_task", "get_budget"]
    sys.exit(main(syms))
