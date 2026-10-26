"""El comando que `leo-mcp init`/`doctor` escriben en la config del cliente MCP tiene que arrancar
de verdad y ser la misma versión que lo escribe."""

from leo_code import __version__, cli

SCRIPTS = "/home/u/proj/.venv/bin"
PINNED = ["uvx", "--from", f"leo-mcp=={__version__}", "leo-mcp"]


def _which(running=None, on_path=None):
    """shutil.which falso: `running` en la carpeta de scripts del entorno, `on_path` en el PATH."""
    return lambda _name, path=None: running if path == SCRIPTS else on_path


def _setup(monkeypatch, **kw):
    monkeypatch.setattr(cli.sysconfig, "get_path", lambda _: SCRIPTS)
    monkeypatch.setattr(cli.shutil, "which", _which(**kw))
    monkeypatch.delenv("LEO_MCP_FROM", raising=False)


def test_uses_the_installed_binary(monkeypatch):
    _setup(monkeypatch, on_path="/home/u/.local/bin/leo-mcp")
    assert cli._launch() == ["/home/u/.local/bin/leo-mcp"]


def test_prefers_the_running_environment_over_path(monkeypatch):
    _setup(monkeypatch, running=f"{SCRIPTS}/leo-mcp", on_path="/usr/bin/leo-mcp")
    assert cli._launch() == [f"{SCRIPTS}/leo-mcp"]


def test_ephemeral_uvx_binary_is_not_written_to_config(monkeypatch):
    cached = r"C:\Users\u\AppData\Local\uv\cache\archive-v0\abc\Scripts\leo-mcp.exe"
    _setup(monkeypatch, running=cached)
    assert cli._launch() == PINNED


def test_without_binary_runs_the_published_version_or_leo_mcp_from(monkeypatch):
    _setup(monkeypatch)
    assert cli._launch() == PINNED
    monkeypatch.setenv("LEO_MCP_FROM", "./dist/leo_mcp-0.3.0-py3-none-any.whl")
    assert cli._launch()[2] == "./dist/leo_mcp-0.3.0-py3-none-any.whl"


def test_never_npx(monkeypatch):
    _setup(monkeypatch)
    assert "npx" not in cli._launch()
