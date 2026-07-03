"""Regression: las citas de las tools del agente son RELATIVAS al repo, nunca el
basename — con basename el agente hacía read_file("loop.py") → No such file."""

from types import SimpleNamespace

from leo_code.rag.agent.tools import ToolRegistry


def _cap(fp, line=10):
    return SimpleNamespace(file_path=fp, start_line=line)


def test_rel_is_repo_relative(tmp_path):
    repo = str(tmp_path)
    fp = str(tmp_path / "pkg" / "mod.py")
    out = ToolRegistry()._rel(_cap(fp), repo)
    assert out == "pkg/mod.py:10"          # relativa, usable en read_file
    assert "\\" not in out


def test_rel_never_bare_basename_outside_repo(tmp_path):
    out = ToolRegistry()._rel(_cap("D:/otro/x.py"), str(tmp_path))
    assert out == "D:/otro/x.py:10"        # fuera del repo: ruta completa, no "x.py"


def test_relativize_graph_render(tmp_path):
    repo = str(tmp_path)
    txt = f"· f (function) @ {tmp_path}\\a\\b.py:3"
    assert ToolRegistry._relativize(txt, repo) == "· f (function) @ a/b.py:3"
