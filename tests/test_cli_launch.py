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


# ---- `leo-mcp init` sobre una config que ya tenía leo-mcp ----

def _init(tmp, client, monkeypatch, launch):
    from argparse import Namespace
    monkeypatch.setattr(cli, "_launch", lambda: launch)
    return cli.cmd_init(Namespace(repo=str(tmp), client=client, no_hook=True))


def test_init_repoints_an_outdated_server_and_keeps_the_others(tmp_path, monkeypatch, capsys):
    import json
    cfg = tmp_path / ".mcp.json"
    old = {"command": "uvx", "args": ["--from", "git+https://github.com/manzzaano/leo-code.git", "leo-mcp"]}
    other = {"command": "otro-mcp", "args": []}
    cfg.write_text(json.dumps({"mcpServers": {"leo-mcp": old, "otro": other}}), encoding="utf-8")
    assert _init(tmp_path, "claude", monkeypatch, PINNED) == 0
    servers = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert servers["leo-mcp"] == {"command": "uvx", "args": PINNED[1:]}
    assert servers["otro"] == other
    assert "Updated" in capsys.readouterr().out


def test_init_leaves_an_up_to_date_server_alone(tmp_path, monkeypatch, capsys):
    assert _init(tmp_path, "cursor", monkeypatch, PINNED) == 0
    cfg = tmp_path / ".cursor" / "mcp.json"
    before = cfg.read_text(encoding="utf-8")
    capsys.readouterr()
    assert _init(tmp_path, "cursor", monkeypatch, PINNED) == 0
    assert cfg.read_text(encoding="utf-8") == before
    assert "already configured" in capsys.readouterr().out


def test_init_repoints_opencode_too(tmp_path, monkeypatch):
    import json
    assert _init(tmp_path, "opencode", monkeypatch, ["/old/leo-mcp"]) == 0
    assert _init(tmp_path, "opencode", monkeypatch, PINNED) == 0
    entry = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))["mcp"]["leo-mcp"]
    assert entry == {"type": "local", "command": PINNED, "enabled": True}


def test_init_repoint_keeps_the_users_own_keys(tmp_path, monkeypatch):
    import json
    cfg = tmp_path / ".mcp.json"
    old = {"command": "/old/leo-mcp", "args": [], "env": {"LEO_SEMANTIC": "1"}}
    cfg.write_text(json.dumps({"mcpServers": {"leo-mcp": old}}), encoding="utf-8")
    assert _init(tmp_path, "claude", monkeypatch, PINNED) == 0
    entry = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["leo-mcp"]
    assert entry == {"command": "uvx", "args": PINNED[1:], "env": {"LEO_SEMANTIC": "1"}}
