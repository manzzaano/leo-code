"""El oráculo (f) mide a qué definición va cada llamada, no solo su nombre.
Con dos métodos homónimos, la resolución por nombre debe salir con aristas falsas."""

import json

from benchmark.resolution_oracle import gate, score_repo, score_snippet


def _snippet(tmp_path, code: str, truth: dict):
    (tmp_path / "main.py").write_text(code, encoding="utf-8")
    (tmp_path / "callgraph.json").write_text(json.dumps(truth), encoding="utf-8")
    return tmp_path


def test_homonyms_count_as_false_edges(tmp_path):
    code = (
        "class A:\n"
        "    def run(self):\n"
        "        pass\n"
        "class B:\n"
        "    def run(self):\n"
        "        pass\n"
        "    def go(self):\n"
        "        self.run()\n"
    )
    truth = {"main": [], "main.A.run": [], "main.B.run": [], "main.B.go": ["main.B.run"]}
    s = score_snippet(_snippet(tmp_path, code, truth))
    assert s["truth"] == {("main.B.go", "main.B.run")}
    assert s["leo"] == {("main.B.go", "main.B.run"), ("main.B.go", "main.A.run")}
    assert s["sound"] and not s["complete"]


def test_repo_judge_uses_jedi_targets(tmp_path):
    (tmp_path / "util.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from util import run as go\n"
        "class A:\n"
        "    def run(self):\n"
        "        pass\n"
        "    def start(self):\n"
        "        self.run()\n"
        "        go()\n",
        encoding="utf-8")
    s = score_repo(str(tmp_path))
    # Se puntúa por sitio de llamada: a nivel de arista los dos errores se taparían.
    assert s["truth"] == {("main.py:A.start", "6:13", "main.py:A.run"),
                          ("main.py:A.start", "7:8", "util.py:run")}
    # self.run() lo resuelve la jerarquía de clases; el alias `go`, el import
    assert s["leo"] == s["truth"]
    assert s["calls"] == 2 and s["exact"] == 2


def test_repo_judge_counts_dynamic_dispatch_apart(tmp_path):
    # jedi no ve overrides: para `self.hook()` en Base solo da Base.hook. Child.hook es un
    # destino real en ejecución (despacho dinámico) y se cuenta aparte, no como falso.
    (tmp_path / "main.py").write_text(
        "class Base:\n"
        "    def run(self):\n"
        "        self.hook()\n"
        "    def hook(self):\n"
        "        pass\n"
        "class Child(Base):\n"
        "    def hook(self):\n"
        "        pass\n"
        "class Other:\n"
        "    def hook(self):\n"
        "        pass\n",
        encoding="utf-8")
    s = score_repo(str(tmp_path))
    assert s["truth"] == {("main.py:Base.run", "3:13", "main.py:Base.hook")}
    assert s["leo"] - s["truth"] == {("main.py:Base.run", "3:13", "main.py:Child.hook")}
    assert s["dispatch"] == {("main.py:Base.run", "3:13", "main.py:Child.hook")}
    assert s["exact"] == 0 and s["exact_dispatch"] == 1


def test_calling_a_parameter_is_not_judged(tmp_path):
    # jedi lleva `g` a su parámetro, que comparte línea con `def`: no es un destino
    (tmp_path / "main.py").write_text("def apply(g):\n    g()\n", encoding="utf-8")
    s = score_repo(str(tmp_path))
    assert s["calls"] == 0 and s["unjudged"] == 1


def test_module_level_callers_are_reported_apart(tmp_path):
    code = "def f():\n    pass\nf()\n"
    truth = {"main": ["main.f"], "main.f": []}
    s = score_snippet(_snippet(tmp_path, code, truth))
    assert s["truth"] == set()
    assert s["module_level"] == 1


def test_by_name_homonyms_are_not_dynamic_dispatch(tmp_path):
    # `forms` re-exporta Field con `import *`: jedi lo sigue, leo no → super() va por nombre.
    # Arr.clean es hermana sin subclase común y Geo.clean es la propia clase: ningún
    # despacho los alcanza desde super() en Geo, así que son falsos, no despacho.
    (tmp_path / "base.py").write_text(
        "class Field:\n    def clean(self):\n        pass\n", encoding="utf-8")
    (tmp_path / "forms.py").write_text("from base import *\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "import forms\n"
        "from base import Field\n"
        "class Geo(forms.Field):\n"
        "    def clean(self):\n"
        "        super().clean()\n"
        "class Arr(Field):\n"
        "    def clean(self):\n"
        "        pass\n",
        encoding="utf-8")
    s = score_repo(str(tmp_path))
    assert s["truth"] == {("main.py:Geo.clean", "5:16", "base.py:Field.clean")}
    assert ("main.py:Geo.clean", "5:16", "main.py:Arr.clean") in s["leo"]
    assert s["dispatch"] == set()


def test_repo_judge_checks_the_product_path_too(tmp_path):
    """who_calls/impact/guard sacan los callers de `callers_of_def`, no de `_scope`: el
    oráculo comprueba que cada destino que jedi ve tiene a su caller ahí."""
    (tmp_path / "a.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("from b import run as other\ndef go():\n    other()\n",
                                   encoding="utf-8")
    s = score_repo(str(tmp_path))
    assert s["product_pairs"] == len(s["truth"]) == 1 and s["product_missed"] == 0


def test_gate_fails_on_any_lost_dependent_or_low_exact():
    ok = {"truth": {1, 2}, "leo": {1, 2, 3}, "calls": 10, "exact": 8,
          "product_pairs": 2, "product_missed": 0}
    assert gate(ok, 70) == []
    assert gate({**ok, "leo": {1, 3}}, 70)                 # un destino perdido
    assert gate({**ok, "product_missed": 1}, 70)            # perdido por who_calls/guard
    assert gate({**ok, "exact": 6}, 70)                     # 60 % < 70 %
    assert gate({**ok, "calls": 0}, 70)                     # oráculo vacuo


def test_judge_error_when_leo_target_shadows_jedis_in_the_mro():
    """django: `super().clean()` en AbstractUser(AbstractBaseUser, PermissionsMixin) va a
    AbstractBaseUser.clean (la MRO la pone antes), pero jedi da Model.clean. No es un
    dependiente perdido: Python nunca llega a Model.clean desde ahí."""
    from benchmark.resolution_oracle import shadowed

    class Scope:
        def _mro(self, ck):
            return ["User", "Base", "Mixin", "Model"]
    assert shadowed(Scope(), "User", True, "Base", "Model")       # super(): Base tapa a Model
    assert not shadowed(Scope(), "User", True, "Model", "Base")   # al revés sí sería pérdida
    assert not shadowed(Scope(), "User", True, "User", "Base")    # super() empieza tras User
    assert not shadowed(Scope(), "User", False, None, "Base")     # leo sin clase: no juzga
