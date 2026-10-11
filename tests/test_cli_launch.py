"""El comando que `leo-mcp init`/`doctor` escriben en la config del cliente MCP tiene que arrancar
de verdad: leo-mcp no está en PyPI ni en npm, así que nunca `npx -y leo-mcp`."""

from leo_code import cli


def test_uses_the_installed_binary(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/home/u/.local/bin/leo-mcp")
    assert cli._launch() == ["/home/u/.local/bin/leo-mcp"]


def test_ephemeral_uvx_binary_is_not_written_to_config(monkeypatch):
    cached = r"C:\Users\u\AppData\Local\uv\cache\archive-v0\abc\Scripts\leo-mcp.exe"
    monkeypatch.setattr(cli.shutil, "which", lambda _: cached)
    monkeypatch.delenv("LEO_MCP_FROM", raising=False)
    assert cli._launch() == ["uvx", "--from", cli.REPO_SOURCE, "leo-mcp"]


def test_without_binary_runs_from_the_repo_or_leo_mcp_from(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.delenv("LEO_MCP_FROM", raising=False)
    assert cli._launch() == ["uvx", "--from", cli.REPO_SOURCE, "leo-mcp"]
    monkeypatch.setenv("LEO_MCP_FROM", "./dist/leo_mcp-0.3.0-py3-none-any.whl")
    assert cli._launch()[2] == "./dist/leo_mcp-0.3.0-py3-none-any.whl"


def test_never_npx(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert "npx" not in cli._launch()
