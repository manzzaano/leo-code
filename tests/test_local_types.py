"""Tipos locales exactos (paso 3): una variable ligada solo a literales o comprensiones
tiene un tipo builtin conocido, así que `x.add()` va fuera del
repo y no a cualquier método `add` del repo por nombre (13/11: `affected = {...};
affected.add()` contaba como llamada a `BM25Index.add`)."""

import pytest

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python

INDEX = "class Index:\n    def add(self, x):\n        pass\n"


def _callees(body: str, extra: str = "") -> set[str]:
    src = INDEX + extra + "\ndef f(y, make):\n" + "".join(f"    {ln}\n" for ln in body.split("; "))
    caps = {c.id: c for c in extract_from_python(src, "p/m.py")}
    return {c.name for c in GraphQuery(caps).callees("f").cites}


@pytest.mark.parametrize("body", [
    "s = {1}; s.add(2)",
    "s = {x for x in y}; s.add(1)",
    "s = []; s.append(1); s.add(1)",
    "s: set[int] = {1}; s.add(1)",
    "s = {1}; s = {2}; s.add(1)",
])
def test_builtin_exacto_no_llama_a_metodos_del_repo(body):
    assert "add" not in _callees(body)


@pytest.mark.parametrize("body", [
    "s = Index(); s.add(1)",            # clase del repo: su método
    "s: Index = Index(); s.add(1)",     # AnnAssign con constructor del repo
    "y.add(1)",                         # parámetro sin tipo: por nombre
    "s = {1}; s = make(); s.add(1)",    # una ligadura desconocida: por nombre
    "s = set(); s.add(1)",              # constructor builtin: por nombre (test_graph_local_types)
])
def test_lo_que_no_es_builtin_exacto_sigue_llegando(body):
    assert "add" in _callees(body)


def test_un_builtin_tapado_por_una_clase_del_repo_va_a_la_del_repo():
    shadow = "class set:\n    def add(self, x):\n        pass\n"
    assert "add" in _callees("s = set(); s.add(1)", shadow)
    assert "add" not in _callees("s = {1}; s.add(1)", shadow)   # un literal es siempre builtin
