"""Resolución de `self.foo()`, `cls.foo()`, `super().foo()` y `Clase.foo()` por la jerarquía
de clases (fase 1, paso 2). Regla: unión, para la clase y cada subclase, del primer `foo`
de su MRO (CHA, Dean et al. 1995); `super()` busca después de la clase que lo encierra.
Lo que no se encuentra sigue por nombre.
"""

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python


def _graph(files: dict[str, str]) -> GraphQuery:
    caps = {}
    for path, src in files.items():
        for c in extract_from_python(src, path):
            caps[c.id] = c
    return GraphQuery(caps)


def _targets(g: GraphQuery, qualified: str) -> set[str]:
    """Destinos de las llamadas del método `Clase.metodo`, como `Clase.metodo`."""
    caller = next(c for c in g.caps.values()
                  if (c.properties or {}).get("qualified") == qualified)
    return {(d.properties or {}).get("qualified") or d.name
            for _, ds in g._callees_of(caller) for d in ds}


UNRELATED = "class Other:\n    def hook(self):\n        pass\n    def helper(self):\n        pass\n"


def test_self_call_goes_to_own_class_not_homonym():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A:\n    def run(self):\n        self.helper()\n"
                "    def helper(self):\n        pass\n"})
    assert _targets(g, "A.run") == {"A.helper"}


def test_template_method_includes_subclass_overrides():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class Base:\n    def run(self):\n        self.hook()\n"
                "    def hook(self):\n        pass\n\n"
                "class Child(Base):\n    def hook(self):\n        pass\n"})
    assert _targets(g, "Base.run") == {"Base.hook", "Child.hook"}


def test_abstract_hook_defined_only_in_subclasses():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class Base:\n    def run(self):\n        self.hook()\n\n"
                "class Child(Base):\n    def hook(self):\n        pass\n"})
    assert _targets(g, "Base.run") == {"Child.hook"}


def test_inherited_method_found_through_mro():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class Base:\n    def helper(self):\n        pass\n\n"
                "class Child(Base):\n    def go(self):\n        self.helper()\n"})
    assert _targets(g, "Child.go") == {"Base.helper"}


def test_super_skips_own_class_and_goes_up_the_mro():
    g = _graph({"p/m.py":
                "class A:\n    def __init__(self):\n        pass\n\n"
                "class B(A):\n    pass\n\n"
                "class C(B):\n    def __init__(self):\n        super().__init__()\n"})
    assert _targets(g, "C.__init__") == {"A.__init__"}


def test_super_can_reach_a_sibling_class():
    # D(Left, Right): MRO D, Left, Right, Base → super() en Left llega a Right.hook
    g = _graph({"p/m.py":
                "class Base:\n    def hook(self):\n        pass\n\n"
                "class Left(Base):\n    def go(self):\n        super().hook()\n\n"
                "class Right(Base):\n    def hook(self):\n        pass\n\n"
                "class D(Left, Right):\n    pass\n"})
    assert _targets(g, "Left.go") == {"Base.hook", "Right.hook"}


def test_base_class_imported_from_another_module():
    g = _graph({"p/o.py": UNRELATED,
                "p/base.py": "class Base:\n    def helper(self):\n        pass\n",
                "p/m.py": "from base import Base\n\n"
                          "class C(Base):\n    def go(self):\n        self.helper()\n"})
    assert _targets(g, "C.go") == {"Base.helper"}


def test_explicit_class_call_has_no_subclass_overrides():
    g = _graph({"p/m.py":
                "class Base:\n    def helper(self):\n        pass\n\n"
                "class Child(Base):\n    def helper(self):\n        Base.helper(self)\n"})
    assert _targets(g, "Child.helper") == {"Base.helper"}


def test_cls_in_classmethod():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A:\n    @classmethod\n    def make(cls):\n        cls.helper()\n"
                "    @classmethod\n    def helper(cls):\n        pass\n"})
    assert _targets(g, "A.make") == {"A.helper"}


def test_staticmethod_first_param_is_not_self():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A:\n    @staticmethod\n    def f(x):\n        x.helper()\n"
                "    def helper(self):\n        pass\n"})
    assert _targets(g, "A.f") == {"A.helper", "Other.helper"}     # por nombre


def test_attribute_callable_stays_by_name():
    # `child` es un atributo asignado (paso 3), no un método: sigue por nombre
    g = _graph({"p/o.py": "class Other:\n    def child(self):\n        pass\n", "p/m.py":
                "class A:\n    def func(self):\n        self.child()\n"})
    assert _targets(g, "A.func") == {"Other.child"}


def test_unresolved_base_falls_back_to_by_name():
    # la base `m.Mixin` viene de un módulo que no se puede seguir: `helper` podría estar
    # ahí (o en un homónimo del repo) → no se descarta nada, sigue por nombre
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "import a.b\n\nclass A(a.b.Mixin):\n    def run(self):\n        self.helper()\n\n"
                "class C(A):\n    def helper(self):\n        pass\n"})
    assert _targets(g, "A.run") == {"C.helper", "Other.helper"}


def test_call_as_base_falls_back_to_by_name():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A(with_meta(object)):\n    def run(self):\n        self.helper()\n\n"
                "class C(A):\n    def helper(self):\n        pass\n"})
    assert _targets(g, "A.run") == {"C.helper", "Other.helper"}


def test_builtin_base_is_known_and_closed():
    # Exception es de fuera: no puede definir un `helper` del repo → resuelve a A.helper
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A(Exception):\n    def run(self):\n        self.helper()\n"
                "    def helper(self):\n        pass\n"})
    assert _targets(g, "A.run") == {"A.helper"}


def test_method_found_before_unresolved_base_is_kept():
    # B(A, X) con X desconocida: MRO B, A, …, X → A.helper va antes que X
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A:\n    def helper(self):\n        pass\n\n"
                "class B(A, unknown.X):\n    def run(self):\n        self.helper()\n"})
    assert _targets(g, "B.run") == {"A.helper"}


def test_cyclic_inheritance_does_not_hang():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A(B):\n    def run(self):\n        self.helper()\n\n"
                "class B(A):\n    def helper(self):\n        pass\n"})
    assert _targets(g, "A.run") == {"B.helper"}


def test_inconsistent_mro_still_finds_method():
    # class C(A, B) con B(A): C3 falla (Python da TypeError); se busca igual sin colgarse
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class A:\n    def helper(self):\n        pass\n\n"
                "class B(A):\n    pass\n\n"
                "class C(A, B):\n    def run(self):\n        self.helper()\n"})
    assert _targets(g, "C.run") == {"A.helper"}


def test_subclass_with_unresolved_base_still_counts_as_override():
    # `class Child(x.y.Base)` no se puede seguir, pero puede ser Base: su hook entra
    g = _graph({"p/o.py": UNRELATED,
                "p/base.py": "class Base:\n    def run(self):\n        self.hook()\n"
                             "    def hook(self):\n        pass\n",
                "p/m.py": "import x.y\n\nclass Child(x.y.Base):\n    def hook(self):\n        pass\n"})
    assert _targets(g, "Base.run") == {"Base.hook", "Child.hook"}


def test_unresolved_subclass_without_override_keeps_resolution():
    # Child (base sin resolver) no define helper: lo hereda de Base, ya cubierto
    g = _graph({"p/o.py": UNRELATED,
                "p/base.py": "class Base:\n    def run(self):\n        self.helper()\n"
                             "    def helper(self):\n        pass\n",
                "p/m.py": "import x.y\n\nclass Child(x.y.Base):\n    def other(self):\n        pass\n"})
    assert _targets(g, "Base.run") == {"Base.helper"}


def test_with_metaclass_base_links_subclass():
    g = _graph({"p/o.py": UNRELATED, "p/m.py":
                "class Base:\n    def run(self):\n        self.hook()\n"
                "    def hook(self):\n        pass\n\n"
                "class Child(with_metaclass(Meta, Base)):\n    def hook(self):\n        pass\n"})
    assert _targets(g, "Base.run") == {"Base.hook", "Child.hook"}

