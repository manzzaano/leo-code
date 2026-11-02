"""Un nombre definido dos veces a nivel de módulo deja de ser único: refgraph no enlaza el
despacho por dict y el guardián marca como «sin test» lo que sí se ejecuta (visto en #9)."""

import ast
from collections import Counter
from pathlib import Path

import leo_code


def test_no_module_defines_a_top_level_name_twice():
    dup = []
    for f in Path(leo_code.__file__).parent.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        dup += [f"{f.name}:{n}" for n, k in names.items() if k > 1]
    assert dup == []
