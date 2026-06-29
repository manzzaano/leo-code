"""Regression: list_files debe dar rutas RELATIVAS, sin ruido (.git/cache/pycache),
acotado y compacto — antes devolvía `str(Tree)` (repr inútil) y volcaba todo el árbol
con rutas absolutas → output gigante → bucle de retrieve_full."""

from pathlib import Path

from leo_code.rag.agent.tools import ToolRegistry


def _make_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    # ruido que NO debe aparecer
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: x\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython.pyc").write_text("x", encoding="utf-8")
    return tmp_path


def test_relative_paths_no_noise(tmp_path):
    repo = _make_repo(tmp_path)
    out = ToolRegistry().list_files({"path": ".", "depth": 3}, str(repo))
    assert "pkg/a.py" in out and "README.md" in out      # rutas relativas, forward-slash
    assert str(repo) not in out                           # NO absolutas
    assert ".git" not in out and "__pycache__" not in out  # ruido filtrado
    assert "rich.tree" not in out.lower()                  # no el repr del objeto Tree


def test_pattern_and_not_found(tmp_path):
    repo = _make_repo(tmp_path)
    out = ToolRegistry().list_files({"path": ".", "pattern": "*.py", "depth": 3}, str(repo))
    assert "a.py" in out and "README.md" not in out
    miss = ToolRegistry().list_files({"path": ".", "pattern": "*.rs", "depth": 3}, str(repo))
    assert "Sin archivos" in miss
