"""Unidad 4b del plan 2026-11-18 (G2/G3): `Guardian.update` pasa el guardián a la generación
siguiente recalculando solo las aristas de referencia afectadas, con `GraphQuery.update`. Tiene
que quedar idéntico al construido desde cero sobre las mismas cápsulas: aristas aumentadas
(orden incluido), índices del grafo, cobertura e informes."""

import random

import pytest

from leo_code.core.boundary import link_http_edges
from leo_code.core.graphquery import GraphQuery
from leo_code.core.guardian import Guardian
from leo_code.rag.indexer import Indexer

FILES = {
    "pkg/__init__.py": "",
    # tabla de despacho: `handler` se referencia, no se llama
    "pkg/table.py": (
        "from pkg.handlers import handler, shared\n\n"
        "_DISPATCH = {'a': handler, 'b': shared}\n\n"
        "def run(k):\n    return _DISPATCH[k]()\n"
    ),
    "pkg/handlers.py": "def handler():\n    return 1\n\ndef shared():\n    return 2\n",
    "pkg/alias.py": (
        "from pkg.handlers import shared as sh\n\n"
        "HOOKS = [sh]\n\n"
        "def fire():\n    return [f() for f in HOOKS]\n"
    ),
    "pkg/other.py": "def shared():\n    return 3\n\ndef lonely():\n    return 4\n",
    "script.py": (
        "import subprocess, sys\n\n"
        "def launch():\n    return subprocess.run([sys.executable, __file__])\n\n"
        "def work():\n    return 5\n\n"
        "if __name__ == '__main__':\n    work()\n"
    ),
    # construir Sub ejecuta el __init__ heredado de Base (ctor_hops), que está en otro archivo
    "pkg/base.py": "class Base:\n    def __init__(self):\n        self.x = 1\n",
    "pkg/sub.py": "from pkg.base import Base\n\nclass Sub(Base):\n    def other(self):\n        return 2\n",
    # nieta: solo nombra a Sub, así que no llama por nombre a nada de base.py
    "pkg/sub2.py": "from pkg.sub import Sub\n\nclass Sub2(Sub):\n    pass\n",
    "tests/test_run.py": (
        "from pkg.table import run\nfrom script import launch\nfrom pkg.sub2 import Sub2\n\n"
        "def test_run():\n    assert run('a') == 1\n\n"
        "def test_launch():\n    launch()\n\n"
        "def test_sub():\n    Sub2()\n"
    ),
}
SYMBOLS = ["handler", "shared", "run", "work", "lonely", "fire", "_DISPATCH", "HOOKS", "launch"]


def _snap_gq(gq):
    ids = lambda d: {k: [c.id for c in v] for k, v in d.items()}
    return (ids(gq.by_name), ids(gq.callers), ids(gq._res), dict(gq._qref),
            {k: set(v) for k, v in gq._fams.items()})


def _snap(g):
    return ({k: list(c.calls) for k, c in g.caps.items()}, _snap_gq(g.gq), g.test_closure(),
            {k: c.id for k, c in g._at.items()}, [g.review(s).render() for s in SYMBOLS])


@pytest.fixture
def repo(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"], verbose=False)
    caps = dict(idx.get_capsules())
    return tmp_path, idx, Guardian(caps, str(tmp_path))


def _edit(root, idx, rel, text):
    p = root / rel
    if text is None:
        p.unlink()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    idx.sync(str(root), since_mtime=float("inf"), paths={str(p)})
    return dict(idx.get_capsules())


def _check(g, root, caps, incremental=None, touched=()):
    g.test_closure()                     # la cobertura vieja ya calculada no puede quedarse
    did = g.update(caps, touched)
    if incremental is not None:
        assert did is incremental
    assert _snap(g) == _snap(Guardian(caps, str(root)))
    return did


def test_sin_cambios_es_incremental(repo):
    root, idx, g = repo
    _check(g, root, dict(idx.get_capsules()), True)


def test_editar_cuerpo_no_reconstruye(repo, monkeypatch):
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/handlers.py", FILES["pkg/handlers.py"] + "\ndef extra():\n    return shared()\n")
    inits = []
    real = GraphQuery.__init__
    monkeypatch.setattr(GraphQuery, "__init__", lambda self, *a, **k: (inits.append(1), real(self, *a, **k))[1])
    g.update(caps)
    assert not inits, "un cambio de cuerpo no debe reconstruir el grafo entero"
    monkeypatch.setattr(GraphQuery, "__init__", real)
    assert _snap(g) == _snap(Guardian(caps, str(root)))


def test_nombre_unico_pasa_a_repetido(repo):
    """Otra def `handler`: deja de ser única y la tabla de otro archivo pierde la arista por
    nombre (y gana la cualificada por el import)."""
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/other.py", FILES["pkg/other.py"] + "\ndef handler():\n    return 9\n")
    _check(g, root, caps, True)


def test_nombre_repetido_pasa_a_unico(repo):
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/other.py", "def lonely():\n    return 4\n")
    _check(g, root, caps, True)


def test_import_con_alias_sigue_a_la_def(repo):
    """`from pkg.handlers import shared as sh`: la arista va a `shared`; si `shared` deja de
    estar en handlers, cambia la arista de alias.py aunque alias.py no se edite."""
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/handlers.py", "def handler():\n    return 1\n")
    _check(g, root, caps)


def test_bloque_main_y_unicidad(repo):
    """El bloque `__main__` se atribuye a quien menciona `__file__`; si `work` se repite,
    `launch` pierde esa arista sin que script.py cambie."""
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/other.py", FILES["pkg/other.py"] + "\ndef work():\n    return 0\n")
    _check(g, root, caps, True)
    caps = _edit(root, idx, "script.py", FILES["script.py"].replace("    work()\n", "    work()\n    lonely()\n"))
    _check(g, root, caps, True)


def test_editar_un_test_cambia_la_cobertura(repo):
    root, idx, g = repo
    assert not g.is_covered("lonely")
    caps = _edit(root, idx, "tests/test_run.py",
                 FILES["tests/test_run.py"] + "\nfrom pkg.other import lonely\n\ndef test_lonely():\n    lonely()\n")
    _check(g, root, caps)
    assert g.is_covered("lonely")
    caps = _edit(root, idx, "tests/test_run.py", FILES["tests/test_run.py"])
    _check(g, root, caps)
    assert not g.is_covered("lonely")


def test_archivo_nuevo_o_borrado_reconstruye(repo):
    root, idx, g = repo
    caps = _edit(root, idx, "pkg/new.py", "def handler():\n    return 7\n")
    _check(g, root, caps, False)
    caps = _edit(root, idx, "pkg/new.py", None)
    _check(g, root, caps, False)


def test_aristas_http_en_capsulas_no_editadas(repo):
    root, idx, g = repo
    caps = _edit(root, idx, "api.py", "@app.get('/api/user')\ndef get_user():\n    return 1\n")
    g = Guardian(caps, str(root))
    caps = _edit(root, idx, "web.py", "def load():\n    return fetch('/api/user')\n")
    g = Guardian(caps, str(root))
    caps = dict(caps)
    touched = set()
    link_http_edges(caps, touched)
    assert touched
    _check(g, root, caps, touched=touched)


def test_orden_de_aristas_determinista(repo):
    """Las de referencia van ordenadas: antes salían en el orden de un set (hash por proceso)."""
    _, idx, g = repo
    orig = idx.get_capsules()
    added = {k: c.calls[len(orig[k].calls):] for k, c in g.caps.items() if "__file__" not in c.content}
    assert len(added[next(k for k, c in g.caps.items() if c.name == "_DISPATCH")]) == 2
    assert all(a == sorted(a) for a in added.values())


def test_diferencial_ediciones_aleatorias(repo):
    root, idx, g = repo
    rnd = random.Random(19)
    bodies = ["return handler()", "return shared()", "return run('a')", "return lonely()",
              "return work()", "return 1", "return _DISPATCH", "return sh"]
    heads = ["", "from pkg.handlers import shared as sh\n", "from pkg.other import shared\n",
             "from pkg.handlers import handler\n", "import pkg.handlers as handler\n"]
    rels = ["pkg/table.py", "pkg/handlers.py", "pkg/alias.py", "pkg/other.py", "script.py",
            "tests/test_run.py"]
    names = ["handler", "shared", "lonely", "work", "fresh"]
    modes = set()
    for i in range(50):
        rel = rnd.choice(rels)
        defs = "\n".join(f"def {rnd.choice(names) if rnd.random() < .5 else f'f{i}_{j}'}():\n"
                         f"    {rnd.choice(bodies)}\n" for j in range(rnd.randint(0, 3)))
        if rel.startswith("tests/"):
            defs += f"\ndef test_{i}():\n    {rnd.choice(bodies)}\n"
        caps = _edit(root, idx, rel, rnd.choice(heads) + FILES[rel] + "\n" + defs)
        modes.add(_check(g, root, caps))
    assert True in modes


def test_init_heredado_en_otro_archivo(repo):
    """Sub2 no cambia, pero su __init__ (de Base, dos niveles arriba) llama ahora a `lonely`."""
    root, idx, g = repo
    assert not g.is_covered("lonely")
    caps = _edit(root, idx, "pkg/base.py", "from pkg.other import lonely\n\nclass Base:\n"
                 "    def __init__(self):\n        self.x = lonely()\n")
    _check(g, root, caps, True)
    assert g.is_covered("lonely")


def test_cierre_tras_editar_reutiliza_las_filas(repo, monkeypatch):
    """G3: tras una edición local solo se recalculan los saltos de lo que puede cambiar."""
    root, idx, g = repo
    g.test_closure()
    total = len(g._rows) + len(g._seeds)
    assert total
    done = []
    real_row, real_seed = Guardian._row, Guardian._seed_row
    monkeypatch.setattr(Guardian, "_row", lambda self, c: done.append(c.id) or real_row(self, c))
    monkeypatch.setattr(Guardian, "_seed_row", lambda self, cs: done.append(cs[0].id) or real_seed(self, cs))
    caps = _edit(root, idx, "pkg/handlers.py", FILES["pkg/handlers.py"].replace("return 1", "return 7"))
    g.update(caps)
    g.test_closure()
    assert 0 < len(done) < total
    monkeypatch.setattr(Guardian, "_row", real_row)
    monkeypatch.setattr(Guardian, "_seed_row", real_seed)
    assert _snap(g) == _snap(Guardian(caps, str(root)))
