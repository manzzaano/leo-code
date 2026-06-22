"""Micro-bench DETERMINISTA del retrieval estructural — cero LLM, cero varianza.

Mide directamente si las tools estructurales exponen los símbolos que las tareas
necesitan (recall). A diferencia del judge LLM, es reproducible al 100% y sirve de
regression guard: si un cambio rompe el indexado de métodos o la agregación, falla.

Uso:  python benchmark/retrieval_bench.py [--repo .]
Sale con código !=0 si el recall < UMBRAL (usable como test en CI).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

UMBRAL = 0.85  # recall mínimo aceptable

# Cada probe: (nombre, tool, args, comprobación).
# comprobación: ("has", substr) | ("count_ge", n) | ("nonempty",)
PROBES = [
    # find_symbol: función top-level (t1/t4)
    ("find func detect_frameworks", "find_symbol", {"pattern": "detect_frameworks"}, ("has", "parser.py")),
    # find_symbol: MÉTODO de clase (t7) — valida el indexado de métodos (Gap 1)
    ("find method _plan", "find_symbol", {"pattern": "_plan"}, ("has", "GoalRunner._plan")),
    ("find class GoalRunner", "find_symbol", {"pattern": "GoalRunner"}, ("has", "goal.py")),
    ("find func _find_block_end", "find_symbol", {"pattern": "_find_block_end"}, ("has", "_find_block_end")),
    # read_symbol: cuerpo de función y de método
    ("read func classify_task", "read_symbol", {"name": "classify_task"}, ("has", "def classify_task")),
    ("read method _plan body", "read_symbol", {"name": "_plan"}, ("has", "GoalRunner._plan")),
    # who_calls / callees / impact: grafo
    ("who_calls compress", "who_calls", {"name": "compress"}, ("nonempty",)),
    ("callees classify_task", "callees", {"name": "classify_task"}, ("nonempty",)),
    ("impact get_budget", "impact", {"name": "get_budget"}, ("nonempty",)),
    # list_by_kind: agregación (t13) — endpoints del server
    ("list endpoints", "list_by_kind", {"kind": "endpoint"}, ("has", "get_context")),
    ("list endpoints count", "list_by_kind", {"kind": "endpoint"}, ("count_ge", 5)),
    ("list methods exist", "list_by_kind", {"kind": "method"}, ("count_ge", 50)),
]


def _check(result: str, kind, *rest) -> bool:
    r = result or ""
    bad = r.startswith("[") and ("no encontrado" in r.lower() or "sin simbolos" in r.lower()
                                  or "no disponible" in r.lower() or "error" in r.lower())
    if kind == "has":
        return rest[0].lower() in r.lower()
    if kind == "nonempty":
        return bool(r.strip()) and not bad
    if kind == "count_ge":
        # primera línea suele ser "N simbolos de tipo ..." → contamos líneas de datos
        lines = [l for l in r.splitlines() if l.strip()]
        return len(lines) - 1 >= rest[0]
    return False


def run(repo: str = ".") -> float:
    from leo_code.rag.agent.tools import ToolRegistry
    from leo_code.rag.indexer import Indexer

    idx = Indexer()
    idx.build(repo, verbose=False)
    tools = ToolRegistry()
    tools.set_index(idx.get_capsules())

    passed = 0
    print(f"{'probe':<28} {'tool':<14} result")
    print("-" * 64)
    for name, tool, args, check in PROBES:
        res = tools.execute(tool, args, repo)
        ok = _check(res, *check)
        passed += ok
        head = res.replace("\n", " ⏎ ")[:34]
        print(f"{'✓' if ok else '✗'} {name:<26} {tool:<14} {head}")

    recall = passed / len(PROBES)
    print("-" * 64)
    print(f"RECALL: {passed}/{len(PROBES)} = {recall:.0%}  (umbral {UMBRAL:.0%})")
    return recall


if __name__ == "__main__":
    repo = "."
    if "--repo" in sys.argv:
        repo = sys.argv[sys.argv.index("--repo") + 1]
    recall = run(repo)
    sys.exit(0 if recall >= UMBRAL else 1)
