"""Paso 3: `x.foo()` con `x = Clase(...)` en la misma función va a la MRO de `Clase`.
Regla de PyCG/pyright: el tipo de una variable es la unión de todo lo que se le asigna.
Solo se resuelve si TODAS las asignaciones de `x` en la función son constructores de
clases del repo; cualquier otra (parámetro, bucle, `x = f()`, global…) → por nombre.
"""

from test_graph_cha import _graph, _targets

DEFS = ("class A:\n    def save(self):\n        pass\n\n"
        "class B:\n    def save(self):\n        pass\n\n"
        "class SubA(A):\n    def save(self):\n        pass\n")


def _run(body: str, extra: str = "") -> set[str]:
    g = _graph({"p/m.py": DEFS + extra + "\nclass Uso:\n    def run(self, p):\n" + body})
    return {t for t in _targets(g, "Uso.run") if t.endswith(".save")}   # sin `A()` mismo


def test_variable_construida_va_a_su_clase():
    assert _run("        x = A()\n        x.save()\n") == {"A.save"}


def test_constructor_no_incluye_subclases():
    assert "SubA.save" not in _run("        x = A()\n        x.save()\n")


def test_varias_asignaciones_dan_la_union():
    assert _run("        x = A()\n        if p:\n            x = B()\n        x.save()\n") == {
        "A.save", "B.save"}


def test_una_asignacion_desconocida_deja_la_llamada_por_nombre():
    assert _run("        x = A()\n        x = p.make()\n        x.save()\n") == {
        "A.save", "B.save", "SubA.save"}


def test_parametro_sigue_por_nombre():
    assert _run("        p = A()\n        p.save()\n") == {"A.save", "B.save", "SubA.save"}


def test_variable_de_bucle_sigue_por_nombre():
    assert _run("        x = A()\n        for x in p:\n            x.save()\n") == {
        "A.save", "B.save", "SubA.save"}


def test_global_sigue_por_nombre():
    assert _run("        global x\n        x = A()\n        x.save()\n") == {
        "A.save", "B.save", "SubA.save"}


def test_clase_importada_de_otro_modulo():
    g = _graph({"p/m.py": DEFS, "p/u.py":
                "from p.m import B\n\ndef run():\n    x = B()\n    x.save()\n"})
    caller = next(c for c in g.caps.values() if c.name == "run")
    assert {d.properties.get("qualified") for _, ds in g._callees_of(caller) for d in ds
            if d.name == "save"} == {"B.save"}


def test_metodo_heredado_por_la_mro():
    assert _run("        x = SubA2()\n        x.save()\n",
                "class SubA2(A):\n    pass\n") == {"A.save"}


def test_no_es_clase_del_repo_sigue_por_nombre():
    assert _run("        x = dict()\n        x.save()\n") == {"A.save", "B.save", "SubA.save"}
