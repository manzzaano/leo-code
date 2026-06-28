"""Regression gate: el grafo de llamadas de leo debe ser SOUND y COMPLETE contra un
oráculo `ast` independiente. Impide que el parser pierda/invente aristas (regresión)."""

import ast

from leo_code.core.parser import extract_from_python, _node_calls


def _oracle(node) -> set[str]:
    out = set()
    for ch in ast.walk(node):
        if isinstance(ch, ast.Call):
            f = ch.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


SAMPLE = '''
import os
def top():
    helper()
    obj.method()
    return os.path.join("a", "b")

class C:
    def m(self):
        self.x()
        free()
'''


def test_function_captures_name_and_attribute_calls():
    caps = {c.name: c for c in extract_from_python(SAMPLE, "x.py")}
    top = set(caps["top"].calls)
    assert {"helper", "method", "join"} <= top      # Name + Attribute, antes faltaba .attr
    m = set(caps["m"].calls)
    assert {"x", "free"} <= m


def test_extraction_matches_independent_oracle():
    tree = ast.parse(SAMPLE)
    nodes = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    caps = {c.name: c for c in extract_from_python(SAMPLE, "x.py")
            if c.type in ("function", "method", "class")}
    for name, c in caps.items():
        node = nodes.get(name.split(".")[-1])
        if node is None:
            continue
        leo, oracle = set(c.calls), _oracle(node)
        assert leo == oracle, f"{name}: falsas={leo-oracle} perdidas={oracle-leo}"


def test_node_calls_helper():
    node = ast.parse("def f():\n a()\n b.c()\n").body[0]
    assert _node_calls(node) == ["a", "c"]


def test_oracle_refuses_vacuous_pass(tmp_path):
    """Un repo vacío/ruta mala NO debe leer 100% — sería un falso pase (cherry-picking)."""
    from benchmark.oracle import run
    p, r, n = run(str(tmp_path))      # dir sin .py → 0 símbolos
    assert (p, r, n) == (0.0, 0.0, 0)  # fallo explícito, no un 1.0 vacuo
