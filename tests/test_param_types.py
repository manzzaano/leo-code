"""Parámetros anotados: `def f(x: Foo)` → `x.m()` va a `m` en Foo y cada subclase (CHA, igual
que `self.m()`), no a cualquier `m` del repo por nombre. Solo formas conservadoras: `Foo`,
`m.Foo`, `"Foo"`, `Foo | None`, `Optional[Foo]`. Protocol, Any, object, uniones y genéricos
siguen por nombre (decisión del 13/11). Un builtin (`x: str`) va fuera del repo salvo que
alguna clase del repo herede de él."""

import pytest

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python

INDEX = ("from typing import Optional, Any, Protocol\n"
         "class Index:\n    def add(self, x):\n        pass\n"
         "class Sub(Index):\n    def add(self, x):\n        pass\n"
         "class Other:\n    def add(self, x):\n        pass\n    def replace(self):\n        pass\n")


def _targets(params: str, body: str, extra: str = "") -> set[str]:
    src = INDEX + extra + f"\ndef f({params}):\n" + "".join(f"    {ln}\n" for ln in body.split("; "))
    caps = {c.id: c for c in extract_from_python(src, "p/m.py")}
    g = GraphQuery(caps)
    caller = next(c for c in caps.values() if c.name == "f" and c.type == "function")
    return {(d.properties or {}).get("qualified") or d.name for _, ds in g._callees_of(caller) for d in ds}


@pytest.mark.parametrize("params", [
    "x: Index", 'x: "Index"', "x: Index | None", "x: None | Index", "x: Optional[Index]",
    "x: Index = None", "*, x: Index",
])
def test_anotado_va_a_la_clase_y_sus_subclases(params):
    assert _targets(params, "x.add(1)") == {"Index.add", "Sub.add"}


def test_subclase_anotada_no_sube_a_la_base_ni_a_hermanas():
    assert _targets("x: Sub", "x.add(1)") == {"Sub.add"}


def test_clase_importada_por_modulo():
    files = {"p/idx.py": "class Index:\n    def add(self, x):\n        pass\n",
             "p/o.py": "class Other:\n    def add(self, x):\n        pass\n",
             "p/m.py": "from p import idx\ndef f(x: idx.Index):\n    x.add(1)\n"}
    caps = {}
    for path, src in files.items():
        caps.update({c.id: c for c in extract_from_python(src, path)})
    g = GraphQuery(caps)
    caller = next(c for c in caps.values() if c.name == "f")
    assert {d.file_path for _, ds in g._callees_of(caller) for d in ds} == {"p/idx.py"}


def test_builtin_anotado_va_fuera_del_repo():
    assert _targets("x: str", "x.replace()") == set()


@pytest.mark.parametrize("params,body,extra", [
    ("x", "x.add(1)", ""),                                  # sin anotar
    ("x: Any", "x.add(1)", ""),
    ("x: object", "x.add(1)", ""),
    ("x: Index | Other", "x.add(1)", ""),                   # unión: fuera del alcance A
    ("x: list[Index]", "x.add(1)", ""),                     # genérico
    ("x: Index", "x = Other(); x.add(1)", ""),              # reasignado
    ("x: Index", "g = lambda x: x.add(1)", ""),             # otro `x` en una lambda
    ("x: Index", "def g(x): x.add(1)", ""),                 # otro `x` en una función anidada
    ("x: P", "x.add(1)", "class P(Protocol):\n    def add(self, x): ...\n"),   # estructural
    ("x: str", "x.replace()", "class S(str):\n    def replace(self):\n        pass\n"),
    ("x: Index", "x.nope()", "class Z:\n    def nope(self):\n        pass\n"),  # no está en la jerarquía
])
def test_lo_demas_sigue_por_nombre(params, body, extra):
    out = _targets(params, body, extra)
    called = body.rsplit(".", 1)[1].split("(")[0]
    assert any(t.endswith("." + called) and not t.startswith(("Index.", "Sub.")) for t in out), out


def _graph_targets(files: dict[str, str], fn: str) -> set[str]:
    caps = {}
    for path, src in files.items():
        caps.update({c.id: c for c in extract_from_python(src, path)})
    g = GraphQuery(caps)
    caller = next(c for c in caps.values() if c.name == fn and c.type == "function")
    return {f"{d.file_path}:{d.name}" for _, ds in g._callees_of(caller) for d in ds}


def test_import_local_distinto_por_funcion_no_comparte_destino():
    files = {"p/a.py": "class C:\n    def run(self):\n        pass\n",
             "p/b.py": "class C:\n    def run(self):\n        pass\n",
             "p/m.py": "def f(x: 'C'):\n    from p.a import C\n    x.run()\n"
                       "def g(x: 'C'):\n    from p.b import C\n    x.run()\n"}
    assert _graph_targets(files, "f") == {"p/a.py:run"}
    assert _graph_targets(files, "g") == {"p/b.py:run"}


def test_builtin_con_subclase_indirecta_en_el_repo_sigue_por_nombre():
    # AppError hereda de ValueError, que hereda de Exception: `e: Exception` puede ser AppError
    extra = "class AppError(ValueError):\n    def render(self):\n        pass\n"
    assert "AppError.render" in _targets("e: Exception", "e.render()", extra)
