"""Resolución de llamadas por ámbito del archivo + tabla de imports (fase 1, paso 1).

Antes el grafo unía cada llamada con TODAS las defs del mismo nombre. Ahora, si la
llamada se puede resolver con los imports del archivo, va solo a su destino; si no,
sigue uniéndose por nombre (nunca se pierde una arista).
"""

from leo_code.core.graphquery import GraphQuery
from leo_code.core.parser import extract_from_python


def _graph(files: dict[str, str]) -> GraphQuery:
    caps = {}
    for path, src in files.items():
        for c in extract_from_python(src, path):
            caps[c.id] = c
    return GraphQuery(caps)


def _callees(g: GraphQuery, name: str) -> set[str]:
    return {f"{c.file}:{c.name}" for c in g.callees(name).cites}


def _callers(g: GraphQuery, name: str) -> set[str]:
    return {c.name for c in g.who_calls(name).cites}


TWO_RUNS = {"p/util.py": "def run():\n    pass\n",
            "p/other.py": "def run():\n    pass\n"}


def test_alias_import_resolves_to_its_module_only():
    g = _graph({**TWO_RUNS, "p/main.py": "from util import run as go\n\ndef main():\n    go()\n"})
    assert _callees(g, "main") == {"p/util.py:run"}
    assert "main" in _callers(g, "run")       # el alias ya no esconde al caller


def test_module_qualified_call_resolves_to_that_module():
    g = _graph({**TWO_RUNS, "p/main.py": "import util as u\n\ndef main():\n    u.run()\n"})
    assert _callees(g, "main") == {"p/util.py:run"}


def test_same_file_def_wins_over_homonym():
    g = _graph({"p/main.py": "def helper():\n    pass\n\ndef main():\n    helper()\n",
                "p/other.py": "def helper():\n    pass\n"})
    assert _callees(g, "main") == {"p/main.py:helper"}


def test_external_import_is_not_a_repo_edge():
    g = _graph({"p/fs.py": "class Fs:\n    def join(self):\n        pass\n",
                "p/main.py": "from os.path import join\n\ndef main():\n    join('a', 'b')\n"})
    assert "main" not in _callers(g, "join")


def test_relative_import_and_reexport_through_init():
    g = _graph({"p/pkg/__init__.py": "from .b import run\n",
                "p/pkg/b.py": "def run():\n    pass\n",
                "p/other.py": "def run():\n    pass\n",
                "p/pkg/a.py": "from .b import run\n\ndef rel():\n    run()\n",
                "p/main.py": "from pkg import run\n\ndef main():\n    run()\n"})
    assert _callees(g, "rel") == {"p/pkg/b.py:run"}
    assert _callees(g, "main") == {"p/pkg/b.py:run"}


def test_function_level_import_resolves():
    g = _graph({**TWO_RUNS, "p/main.py": "def main():\n    from util import run\n    run()\n"})
    assert _callees(g, "main") == {"p/util.py:run"}


def test_unresolved_receiver_stays_by_name():
    g = _graph({**TWO_RUNS, "p/main.py": "def main(obj):\n    obj.run()\n"})
    assert _callees(g, "main") == {"p/util.py:run", "p/other.py:run"}
    assert "main" in _callers(g, "run")


def test_impact_follows_resolved_edges_only():
    g = _graph({**TWO_RUNS,
                "p/a.py": "from util import run\n\ndef a():\n    run()\n",
                "p/b.py": "from other import run\n\ndef b():\n    run()\n"})
    # impact por nombre sigue juntando ambos `run` (la consulta es por nombre)…
    assert {c.name for c in g.impact("run").cites} == {"a", "b"}
    # …pero cada caller llega solo a su destino real
    assert _callees(g, "a") == {"p/util.py:run"}
    assert _callees(g, "b") == {"p/other.py:run"}


def test_builtin_call_is_not_a_repo_edge():
    g = _graph({"p/fmt.py": "class Fmt:\n    def print(self):\n        pass\n",
                "p/main.py": "def main():\n    print('x')\n"})
    assert "main" not in _callers(g, "print")


def test_from_dot_import_resolves_to_package_init():
    g = _graph({"p/pkg/__init__.py": "def run():\n    pass\n",
                "p/other.py": "def run():\n    pass\n",
                "p/pkg/a.py": "from . import run\n\ndef rel():\n    run()\n"})
    assert _callees(g, "rel") == {"p/pkg/__init__.py:run"}


def test_function_level_import_shadows_file_import():
    g = _graph({**TWO_RUNS, "p/main.py": "from util import run\n\n"
                "def main():\n    from other import run\n    run()\n"})
    assert _callees(g, "main") == {"p/other.py:run"}


def test_reclassified_top_level_def_still_resolves():
    # el clasificador puede reetiquetar una def (middleware, model, endpoint…)
    from leo_code.core.parser import extract_from_python
    caps = {}
    for path, src in {**TWO_RUNS, "p/main.py": "from util import run\n\ndef main():\n    run()\n"}.items():
        for c in extract_from_python(src, path):
            if path == "p/util.py" and c.name == "run":
                c.type = "middleware"
            caps[c.id] = c
    assert _callees(GraphQuery(caps), "main") == {"p/util.py:run"}


def test_refs_added_after_parsing_stay_by_name():
    # refgraph/boundary añaden nombres a `calls` tras parsear: no tienen forma → por nombre
    from leo_code.core.parser import extract_from_python
    caps = {}
    for path, src in {"p/h.py": "def handler():\n    pass\n",
                      "p/main.py": "def main():\n    pass\n"}.items():
        for c in extract_from_python(src, path):
            caps[c.id] = c
    main = next(c for c in caps.values() if c.name == "main")
    main.calls.append("handler")
    assert "main" in _callers(GraphQuery(caps), "handler")


# ---- impact por definición (revisión #5, 27/10) ----
TARGET = {"p/core.py": "def target():\n    pass\n"}


def test_impact_keeps_homonymous_dependents():
    # antes se deduplicaba por nombre base: solo salía uno de los dos `run`
    files = {**TARGET,
             "p/a.py": "from core import target\n\ndef run():\n    target()\n",
             "p/b.py": "from core import target\n\ndef run():\n    target()\n"}
    g = _graph(files)
    assert sorted(c.file for c in g.impact("target").cites) == ["p/a.py", "p/b.py"]
    # y no depende del orden en que llegan las cápsulas
    rev = GraphQuery(dict(reversed(list(g.caps.items()))))
    assert [str(c) for c in rev.impact("target").cites] == [str(c) for c in g.impact("target").cites]


def test_impact_does_not_follow_homonyms_of_dependents():
    g = _graph({**TARGET,
                "p/svc.py": "from core import target\n\ndef helper():\n    target()\n",
                "p/t.py": "def helper():\n    pass\n\ndef test_x():\n    helper()\n"})
    assert {c.name for c in g.impact("target").cites} == {"helper"}   # test_x llama a SU helper


def test_impact_of_class_method_starts_from_that_definition():
    g = _graph({"p/m.py": "class A:\n    def save(self):\n        pass\n"
                          "class B:\n    def save(self):\n        pass\n"
                          "def use_a():\n    a = A()\n    a.save()\n"
                          "def use_b():\n    b = B()\n    b.save()\n"})
    assert {c.name for c in g.impact("A.save").cites} == {"use_a"}


# ---- trace por definición (revisión #6, 27/10) ----
# b.py va primero: antes cada salto se citaba con la PRIMERA def del nombre (B.get)
GETS = {"p/b.py": "class B:\n    def get(self):\n        return 1\n",
        "p/a.py": "class A:\n    def get(self):\n        return helper_a()\n"
                  "def helper_a():\n    return target()\n",
        "p/target.py": "def target():\n    pass\n",
        "p/main.py": "from a import A\n\ndef main():\n    x = A()\n    return x.get()\n"
                     "def loose(obj):\n    return obj.get()\n"}


def test_trace_cites_the_definitions_it_walks():
    p = _graph(GETS).trace("main", "target")
    assert [(c.file, c.line) for c in p.cites] == [("p/main.py", 3), ("p/a.py", 2), ("p/a.py", 4),
                                                   ("p/target.py", 1)]
    assert str(p.cites[1]) == "A.get (method) @ p/a.py:2 ← called at :5"


def test_trace_marks_hops_that_go_by_name():
    p = _graph(GETS).trace("loose", "target")
    assert str(p.cites[1]) == "A.get (method) @ p/a.py:2 ← called at :7 ≈ by name, 2 candidates"


def test_trace_from_class_method_and_homonym_note():
    g = _graph(GETS)
    assert not g.trace("B.get", "target").found
    p = g.trace("get", "target")
    assert p.found and "`get` matches 2 definitions (this path uses p/a.py:2)" in p.render()


def test_trace_does_not_depend_on_capsule_order():
    g = _graph(GETS)
    rev = GraphQuery(dict(reversed(list(g.caps.items()))))
    for a, b in (("main", "target"), ("loose", "target"), ("get", "target")):
        assert rev.trace(a, b).render() == g.trace(a, b).render()


def test_trace_marks_by_name_hops_even_with_one_candidate():
    # `Path(x).resolve()` de pathlib cae por nombre en el único `resolve` del repo
    p = _graph({"p/s.py": "class Scope:\n    def resolve(self):\n        return 1\n",
                "p/m.py": "def run(x):\n    return Path(x).resolve()\n"}).trace("run", "resolve")
    assert str(p.cites[1]) == "Scope.resolve (method) @ p/s.py:2 ← called at :2 ≈ by name"
