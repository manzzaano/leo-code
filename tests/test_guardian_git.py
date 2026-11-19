"""`git_diff` y `guard_repo` (el camino de `python -m leo_code.core.guardian --base` en CI) sobre un
repo git temporal: qué diff se revisa en cada modo y qué informa el guardián del cambio."""

import subprocess

import pytest

from leo_code.core.guardian import git_diff, guard_repo

# helper y tested pegadas: el hunk de `git diff -U3` trae la otra como contexto
FILES = {
    "app/core.py": "def helper():\n    return 1\n\n\ndef tested():\n    return 2\n",
    "app/use.py": "from app.core import helper\n\n\ndef caller():\n    return helper()\n",
    "tests/test_core.py": "from app.core import tested\n\n\ndef test_tested():\n    assert tested() == 2\n",
}


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    return tmp_path


def _change(root, rel, old, new):
    p = root / rel
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_git_diff_working_tree_staged_y_base(repo):
    assert git_diff(str(repo)) == ""
    _change(repo, "app/core.py", "return 1", "return 10")
    assert "+    return 10" in git_diff(str(repo))
    assert git_diff(str(repo), staged=True) == ""          # aún no está en el índice
    _git(repo, "add", "app/core.py")
    assert git_diff(str(repo)) == ""
    assert "+    return 10" in git_diff(str(repo), staged=True)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "cambio")
    assert "+    return 10" in git_diff(str(repo), base="HEAD~1")


def test_git_diff_fuera_de_un_repo_da_vacio(tmp_path):
    assert git_diff(str(tmp_path)) == ""


def test_guard_repo_sin_cambios(repo):
    reports, summary = guard_repo(str(repo))
    assert reports == [] and summary == {"changed": 0, "affected": 0, "uncovered_risk": 0}


def test_guard_repo_marca_dependiente_sin_test(repo):
    _change(repo, "app/core.py", "return 1", "return 10")
    reports, summary = guard_repo(str(repo))
    assert [r.symbol for r in reports] == ["helper"]
    r = reports[0]
    assert not r.changed_covered
    assert [a.cite.name for a in r.affected] == ["caller"]
    assert [a.cite.name for a in r.uncovered] == ["caller"]
    assert summary == {"changed": 1, "affected": 1, "uncovered_risk": 1}


def test_guard_repo_cambio_cubierto_contra_base(repo):
    _change(repo, "app/core.py", "return 2", "return 20")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "cambio")
    assert guard_repo(str(repo))[0] == []                  # working tree limpio
    reports, _ = guard_repo(str(repo), base="HEAD~1")
    assert [r.symbol for r in reports] == ["tested"]
    assert reports[0].changed_covered


def _guardian(repo):
    from leo_code.core.guardian import Guardian
    from leo_code.rag.indexer import Indexer
    idx = Indexer()
    idx.build(str(repo), languages=["python"], verbose=False)
    return Guardian(dict(idx.get_capsules()), str(repo))


def test_changed_symbols_no_cuenta_el_contexto(repo):
    """Solo las líneas + y -: las de contexto del hunk son de funciones vecinas sin tocar."""
    _change(repo, "app/core.py", "return 2", "return 20")
    assert _guardian(repo).changed_symbols(git_diff(str(repo))) == ["tested"]


def test_changed_symbols_borrado_dentro_de_una_funcion(repo):
    _change(repo, "app/use.py", "    return helper()\n", "    x = helper()\n    return x\n")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "dos líneas")
    _change(repo, "app/use.py", "    x = helper()\n", "")       # solo un «-», ningún «+»
    assert _guardian(repo).changed_symbols(git_diff(str(repo))) == ["caller"]


def test_changed_symbols_varios_archivos(repo):
    _change(repo, "app/core.py", "return 1", "return 10")
    _change(repo, "app/use.py", "return helper()", "return helper() + 1")
    assert sorted(_guardian(repo).changed_symbols(git_diff(str(repo)))) == ["caller", "helper"]


def _staged(repo):
    _git(repo, "add", "-A")
    return _guardian(repo).changed_symbols(git_diff(str(repo), staged=True))


def test_changed_symbols_ruta_no_ascii(repo):
    """git cita la ruta con escapes octales: `+++ "b/\303\261/m.py"`."""
    (repo / "ñ").mkdir()
    (repo / "ñ" / "m.py").write_text("def uno():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ñ")
    _change(repo, "ñ/m.py", "return 1", "return 9")
    assert _staged(repo) == ["uno"]


def test_changed_symbols_mismo_nombre_en_otra_carpeta(repo):
    (repo / "otra").mkdir()
    (repo / "otra" / "core.py").write_text(FILES["app/core.py"].replace("helper", "ajeno"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "otra")
    _change(repo, "otra/core.py", "return 1", "return 9")
    assert _staged(repo) == ["ajeno"]


def test_changed_symbols_linea_que_parece_cabecera(repo):
    """Una línea añadida `++ b/x.py` sale en el diff como `+++ b/x.py`: es contenido, no cabecera."""
    _change(repo, "app/use.py", "def caller():\n", 'def caller():\n    """doc\n\n\n\n\n"""\n')
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "doc")
    # única línea del diff: dentro de caller; leída como cabecera iría a la línea 9 de core.py
    _change(repo, "app/use.py", '\n\n\n\n"""\n', '\n\n\n\n++ b/app/core.py\n"""\n')
    assert _staged(repo) == ["caller"]


def test_changed_symbols_renombre_borrado_y_binario(repo):
    (repo / "app" / "core.py").rename(repo / "app" / "nucleo.py")
    _change(repo, "app/nucleo.py", "return 2", "return 20")
    (repo / "tests" / "test_core.py").unlink()
    (repo / "logo.bin").write_bytes(b"\0\1\2")
    assert _staged(repo) == ["tested"]


def test_changed_symbols_import_no_es_simbolo_cambiado(repo):
    """Un import nuevo no es código cambiado: su cápsula lleva el tipo de lo importado y
    salía como «NO test» (el test nuevo que importa `helper` marcaba `app.core.helper`)."""
    (repo / "tests" / "test_use.py").write_text(
        "from app.core import helper\n\n\ndef test_helper():\n    assert helper() == 1\n",
        encoding="utf-8")
    assert _staged(repo) == []


def test_changed_symbols_cuenta_constantes(repo):
    """Constantes y variables de módulo son nodos del grafo (#7 B): cambiarlas es un cambio."""
    _change(repo, "app/core.py", "def helper():", "LIMIT = 3\n\n\ndef helper():")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "const")
    _change(repo, "app/core.py", "LIMIT = 3", "LIMIT = 4")
    assert _staged(repo) == ["LIMIT"]
