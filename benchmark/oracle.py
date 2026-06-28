"""Oráculo INDEPENDIENTE del grafo de llamadas — verifica que leo es SOUND y COMPLETE.

Re-deriva las aristas de llamada con `ast` por un camino SEPARADO del parser de leo
(re-parsea cada archivo, localiza cada def por (nombre,línea) y recoge las llamadas
Name `foo()` + Attribute `obj.foo()`). Compara contra `capsule.calls` de leo:

  precisión = aristas de leo que existen en el oráculo  (mide aristas FALSAS)
  recall    = aristas del oráculo que leo encontró      (mide aristas PERDIDAS)

Sound = sin aristas falsas (precisión 1.0). Complete = sin aristas perdidas (recall 1.0).
Si algo <100%, imprime los símbolos y las aristas en disputa para arreglar el parser.

Uso:  python benchmark/oracle.py [--repo .]
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_DEF = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _oracle_calls(node) -> set[str]:
    out = set()
    for ch in ast.walk(node):
        if isinstance(ch, ast.Call):
            f = ch.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _file_nodes(path: Path) -> dict:
    """(nombre, línea) -> nodo def, re-parseando el archivo de forma independiente."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, _DEF):
            out[(node.name, node.lineno)] = node
    return out


def run(repo: str = ".", verbose_limit: int = 12):
    from leo_code.rag.indexer import Indexer
    idx = Indexer()
    idx.build(repo, verbose=False)
    caps = idx.get_capsules()

    # cápsulas que representan defs Python con cuerpo (las que tienen aristas de llamada)
    code_types = {"function", "async_function", "method", "class", "dataclass", "exception", "test"}
    by_file: dict[str, list] = {}
    for c in caps.values():
        if c.type in code_types and (c.file_path or "").endswith(".py"):
            by_file.setdefault(c.file_path, []).append(c)

    tot_leo = tot_oracle = tot_inter = 0
    symbols = 0
    false_edges = []   # leo dice X pero el oráculo no (precisión)
    missed_edges = []  # el oráculo tiene X y leo no (recall)

    for fpath, cs in by_file.items():
        nodes = _file_nodes(Path(fpath))
        for c in cs:
            node = nodes.get((c.name.split(".")[-1], c.start_line))
            if node is None:
                continue   # def no localizable (import-pseudo, etc.) → fuera de alcance
            oracle = _oracle_calls(node)
            leo = set(c.calls or [])
            inter = leo & oracle
            symbols += 1
            tot_leo += len(leo); tot_oracle += len(oracle); tot_inter += len(inter)
            for e in leo - oracle:
                false_edges.append((c.name, c.start_line, e))
            for e in oracle - leo:
                missed_edges.append((c.name, c.start_line, e))

    # Anti-pase-vacuo: un índice vacío NO es "100% sound+complete", es un fallo de setup
    # (ruta mala, repo no clonado). Sin esto un repo inexistente leería IRREFUTABLE.
    if symbols == 0 or tot_oracle == 0:
        print(f"❌ ORÁCULO VACUO: 0 símbolos/aristas verificados en {repo!r} "
              "(ruta mala o repo sin .py). NO es un pase — es fallo de setup.")
        return 0.0, 0.0, 0

    precision = tot_inter / tot_leo if tot_leo else 1.0
    recall = tot_inter / tot_oracle if tot_oracle else 1.0
    print(f"símbolos verificados: {symbols:,}  ·  aristas leo: {tot_leo:,}  ·  oráculo: {tot_oracle:,}")
    print(f"PRECISIÓN (sin aristas falsas):   {precision*100:.3f}%  ({len(false_edges)} falsas)")
    print(f"RECALL    (sin aristas perdidas): {recall*100:.3f}%  ({len(missed_edges)} perdidas)")
    if false_edges:
        print("  falsas (leo dice, oráculo no):")
        for n, ln, e in false_edges[:verbose_limit]:
            print(f"    {n}:{ln}  → {e}")
    if missed_edges:
        print("  perdidas (oráculo sí, leo no):")
        for n, ln, e in missed_edges[:verbose_limit]:
            print(f"    {n}:{ln}  → {e}")
    return precision, recall, symbols


if __name__ == "__main__":
    repo = "."
    if "--repo" in sys.argv:
        repo = sys.argv[sys.argv.index("--repo") + 1]
    p, r, n = run(repo)
    sys.exit(0 if (p >= 0.999 and r >= 0.999) else 1)
