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
