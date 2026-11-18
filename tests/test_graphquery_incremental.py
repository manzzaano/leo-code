"""Unidad 3 del plan 2026-11-18: `GraphQuery.update` re-resuelve solo los archivos editados y
los que los consultaron. El grafo resultante tiene que ser idéntico al construido desde cero
sobre las mismas cápsulas, orden de las listas incluido (de él salen las citas)."""

import random

import pytest

from leo_code.core.boundary import link_http_edges
from leo_code.core.graphquery import GraphQuery, _PyScope
from leo_code.rag.indexer import Indexer

FILES = {
    "pkg/__init__.py": "from .core import run as start\nfrom .base import Base\n",
    "pkg/base.py": (
        "class Base:\n"
        "    def save(self):\n        return self.clean()\n"
        "    def clean(self):\n        return 1\n"
    ),
    "pkg/core.py": (
        "from .base import Base\n"
        "from .util import helper\n\n"
        "class Model(Base):\n"
        "    def clean(self):\n        return helper()\n\n"
        "def run(m: Base):\n    m.save()\n    return helper()\n"
    ),
    "pkg/util.py": "def helper():\n    return 2\n\ndef unused():\n    return 3\n",
    "app.py": (
        "from pkg import start, Base\n"
        "import pkg.util as u\n\n"
        "def main():\n    start(Base())\n    u.helper()\n    return leaf()\n\n"
        "def leaf():\n    return 0\n"
    ),
    "leaf.py": "def alone():\n    return len([1])\n",
}


def _snap(gq):
    ids = lambda d: {k: [c.id for c in v] for k, v in d.items()}
    return (ids(gq.by_name), ids(gq.callers), ids(gq._res), dict(gq._qref),
            {k: set(v) for k, v in gq._fams.items()})


@pytest.fixture
def repo(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"], verbose=False)
    gq = GraphQuery(_caps(idx))
    return tmp_path, idx, gq


def _caps(idx):
    return dict(idx.get_capsules())


def _edit(root, idx, rel, text):
    p = root / rel
    if text is None:
        p.unlink()
    else:
        p.write_text(text, encoding="utf-8")
    idx.sync(str(root), since_mtime=float("inf"), paths={str(p)})
    return _caps(idx)


def _check(gq, caps, incremental):
    did = gq.update(caps)
    assert did is incremental
    assert _snap(gq) == _snap(GraphQuery(caps))
    assert gq.caps is caps


def test_sin_cambios_no_hace_nada(repo):
    _, idx, gq = repo
    _check(gq, _caps(idx), True)


def test_editar_el_cuerpo_es_incremental_e_identico(repo):
    root, idx, gq = repo
    caps = _edit(root, idx, "pkg/util.py",
                 "def helper():\n    return unused()\n\ndef unused():\n    return 3\n")
    _check(gq, caps, True)


def test_editar_un_archivo_que_nadie_consulta_solo_resuelve_ese(repo, monkeypatch):
    root, idx, gq = repo
    caps = _edit(root, idx, "leaf.py", "def alone():\n    return max([1])\n")
    seen = []
    real = _PyScope.resolve
    monkeypatch.setattr(_PyScope, "resolve",
                        lambda self, c, *a, **k: (seen.append(c.file_path), real(self, c, *a, **k))[1])
    _check(gq, caps, True)
    built_from_zero = len(seen) - len([f for f in seen if f.endswith("leaf.py")])
    # update resuelve solo leaf.py (dos veces: lo viejo y lo nuevo); el resto lo pone el
    # GraphQuery desde cero de la comparación
    assert built_from_zero == sum(1 for c in caps.values()
                                  if (c.properties or {}).get("call_forms") is not None
                                  and not c.file_path.endswith("leaf.py"))


def test_renombrar_una_def_importada_cambia_a_sus_llamantes(repo):
    root, idx, gq = repo
    caps = _edit(root, idx, "pkg/util.py", "def helper2():\n    return 2\n\ndef unused():\n    return 3\n")
    _check(gq, caps, True)
    assert not any(c.name == "main" for c in gq._res.get("helper", ()))


def test_cambiar_un_reexport_del_paquete(repo):
    root, idx, gq = repo
    caps = _edit(root, idx, "pkg/__init__.py", "from .util import helper as start\nfrom .base import Base\n")
    _check(gq, caps, True)
    assert any(c.name == "main" for c in gq._res.get("helper", ()))


def test_metodo_nuevo_en_la_base_cambia_el_despacho(repo):
    root, idx, gq = repo
    caps = _edit(root, idx, "pkg/base.py", FILES["pkg/base.py"] + "    def extra(self):\n        return self.save()\n")
    _check(gq, caps, True)


def test_quitar_el_override_de_la_subclase(repo):
    root, idx, gq = repo
    caps = _edit(root, idx, "pkg/core.py", FILES["pkg/core.py"].replace(
        "    def clean(self):\n        return helper()\n", "    pass\n"))
    _check(gq, caps, True)


@pytest.mark.parametrize("rel,text", [
    ("pkg/util.py", FILES["pkg/util.py"] + "\nclass Extra(Exception):\n    pass\n"),   # clase nueva
    ("pkg/core.py", FILES["pkg/core.py"].replace("class Model(Base)", "class Model")),  # bases
    ("pkg/extra.py", "def helper():\n    return 9\n"),                                 # archivo nuevo
    ("leaf.py", None),                                                                  # archivo borrado
])
def test_cambios_de_estructura_reconstruyen_entero(repo, rel, text):
    root, idx, gq = repo
    caps = _edit(root, idx, rel, text)
    _check(gq, caps, False)


def test_aristas_http_nuevas_en_capsulas_no_editadas(repo):
    """link_http_edges muta en sitio las cápsulas cliente: sin `touched`, update no lo vería."""
    root, idx, gq = repo
    caps = _edit(root, idx, "api.py", "@app.get('/api/user')\ndef get_user():\n    return 1\n")
    gq = GraphQuery(caps)
    caps = _edit(root, idx, "web.py", "def load():\n    return fetch('/api/user')\n")
    gq.update(caps)
    caps = dict(caps)
    touched = set()
    link_http_edges(caps, touched)
    assert touched
    gq.update(caps, touched)
    assert _snap(gq) == _snap(GraphQuery(caps))


def test_diferencial_ediciones_aleatorias(repo):
    """Ediciones de cuerpo, defs, imports y clases al azar: siempre igual que desde cero."""
    root, idx, gq = repo
    rnd = random.Random(18)
    bodies = ["return helper()", "return start(1)", "return self.clean()", "return u.helper()",
              "return leaf()", "return Base().save()", "return unused()", "return 1"]
    extra = ["", "from .util import unused\n", "from pkg.util import helper as leaf\n",
             "import pkg.core as leaf\n", "class Sub(Base):\n    def save(self):\n        return 5\n"]
    rels = ["pkg/util.py", "pkg/core.py", "pkg/base.py", "app.py", "leaf.py", "pkg/__init__.py"]
    modes = set()
    for _ in range(40):
        rel = rnd.choice(rels)
        head = rnd.choice(extra) if rel != "pkg/__init__.py" else rnd.choice(
            ["from .core import run as start\n", "from .util import helper as start\n"])
        base = "from .base import Base\n" if rel.startswith("pkg/") and rel != "pkg/base.py" else (
            "from pkg import start, Base\nimport pkg.util as u\n" if rel in ("app.py", "leaf.py") else "")
        body = "\n".join(f"def f{i}():\n    {rnd.choice(bodies)}\n" for i in range(rnd.randint(0, 3)))
        caps = _edit(root, idx, rel, base + head + "\n" + FILES[rel] + "\n" + body)
        modes.add(gq.update(caps))
        assert _snap(gq) == _snap(GraphQuery(caps)), rel
    assert modes == {True, False}, "el diferencial tiene que pasar por los dos caminos"
