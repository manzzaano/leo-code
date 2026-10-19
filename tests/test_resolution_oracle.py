"""El oráculo (f) mide a qué definición va cada llamada, no solo su nombre.
Con dos métodos homónimos, la resolución por nombre debe salir con aristas falsas."""

import json

from benchmark.resolution_oracle import score_repo, score_snippet


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
    # self.run() aún va por nombre (une también util.run); el alias `go` lo resuelve el import
    assert s["leo"] == {("main.py:A.start", "6:13", "main.py:A.run"),
                        ("main.py:A.start", "6:13", "util.py:run"),
                        ("main.py:A.start", "7:8", "util.py:run")}
    assert s["calls"] == 2 and s["exact"] == 1


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
