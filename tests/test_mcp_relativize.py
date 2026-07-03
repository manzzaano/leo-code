"""Regression: las citas que salen por MCP van RELATIVAS al repo (antes: ruta
absoluta Windows en cada línea → tokens desperdiciados en el cliente)."""

from leo_code.server.mcp_server import _relativize


def test_strips_repo_prefix_and_backslashes():
    repo = r"C:\Users\x\proj"
    txt = r"· f (function) @ C:\Users\x\proj\pkg\a.py:10"
    assert _relativize(txt, repo) == "· f (function) @ pkg/a.py:10"


def test_leaves_foreign_paths_untouched():
    assert _relativize("· g @ D:/otro/b.py:1", r"C:\Users\x\proj") == "· g @ D:/otro/b.py:1"
