"""`git_diff` y `guard_repo` (el camino de `python -m leo_code.core.guardian --base` en CI) sobre un
repo git temporal: qué diff se revisa en cada modo y qué informa el guardián del cambio."""

import subprocess

import pytest

from leo_code.core.guardian import git_diff, guard_repo

# más de 3 líneas entre funciones: el hunk de `git diff -U3` incluye contexto y
# `changed_symbols` cuenta todo el hunk, así que funciones pegadas saldrían ambas como cambiadas
FILES = {
    "app/core.py": "def helper():\n    return 1\n\n\n\n\n\ndef tested():\n    return 2\n",
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
