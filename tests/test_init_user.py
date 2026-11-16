"""`leo-mcp init --user`: leo-mcp en Claude Code para todos los repos, sin tocar ninguno.

El MCP se registra con `claude mcp add --scope user` (Claude Code es dueño de
~/.claude.json); los hooks van a ~/.claude/settings.json. Aquí `claude` es un doble.
"""

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from leo_code import cli

CLAUDE = "/bin/claude"
LAUNCH = ["/bin/leo-mcp"]
UV_CACHE_PY = r"C:\Users\u\AppData\Local\uv\cache\archive-v0\abc\Scripts\python.exe"


class Env(Namespace):
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(settings=tmp_path / "home" / ".claude" / "settings.json", calls=[],
            rc=0, out="Added stdio MCP server leo-mcp", err="", claude=CLAUDE,
            repo=tmp_path / "repo")
    e.repo.mkdir()
    monkeypatch.setattr(cli, "_user_settings", lambda: e.settings)
    monkeypatch.setattr(cli, "_launch", lambda: list(LAUNCH))
    real_which = cli.shutil.which
    monkeypatch.setattr(cli.shutil, "which",
                        lambda name, *a, **k: e.claude if name == "claude" else real_which(name, *a, **k))

    def fake_run(cmd, *a, **k):
        e.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, e.rc, e.out, e.err)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return e


def _init_user(e, **kw):
    args = Namespace(repo=str(e.repo), client=kw.get("client", "claude"),
                     no_hook=kw.get("no_hook", False), user=True)
    return cli.cmd_init(args)


def _hooks(e):
    return json.loads(e.settings.read_text(encoding="utf-8"))["hooks"]


def test_registra_con_scope_user_e_instala_los_dos_hooks(env):
    assert _init_user(env) == 0
    assert env.calls == [[CLAUDE, "mcp", "add", "--scope", "user", "leo-mcp", "--", *LAUNCH]]
    hooks = _hooks(env)
    assert hooks["PreToolUse"][0]["matcher"] == "Edit|Write"
    assert "leo_code.guard_hook" in hooks["PreToolUse"][0]["hooks"][0]["command"]
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume"
    assert "leo_code.index_hook" in hooks["SessionStart"][0]["hooks"][0]["command"]


def test_idempotente(env, capsys):
    _init_user(env)
    env.rc, env.out = 1, "MCP server leo-mcp already exists in user config"
    capsys.readouterr()
    assert _init_user(env) == 0
    hooks = _hooks(env)
    assert len(hooks["PreToolUse"]) == 1 and len(hooks["SessionStart"]) == 1
    assert "already" in capsys.readouterr().out


def test_ya_registrado_no_se_toca(env, capsys):
    env.rc, env.out, env.err = 1, "", "MCP server leo-mcp already exists in user config"
    assert _init_user(env) == 0
    out = capsys.readouterr().out
    assert "already registered" in out
    assert not any("remove" in c for c in env.calls), "nunca borra un registro del usuario"


def test_sin_claude_imprime_el_comando_e_instala_los_hooks(env, capsys):
    env.claude = None
    assert _init_user(env) == 0
    assert env.calls == []
    assert "claude mcp add --scope user leo-mcp -- /bin/leo-mcp" in capsys.readouterr().out
    assert "SessionStart" in _hooks(env)


def test_claude_falla_por_otra_razon(env, capsys):
    env.rc, env.out, env.err = 1, "", "Error: not logged in"
    assert _init_user(env) == 0
    out = capsys.readouterr().out
    assert "claude mcp add --scope user leo-mcp -- /bin/leo-mcp" in out
    assert "already" not in out


def test_claude_que_no_responde(env, monkeypatch, capsys):
    def colgado(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd, 60)
    monkeypatch.setattr(cli.subprocess, "run", colgado)
    assert _init_user(env) == 0
    assert "claude mcp add --scope user" in capsys.readouterr().out


def test_crea_settings_si_no_hay_carpeta(env):
    assert not env.settings.parent.exists()
    assert _init_user(env) == 0
    assert env.settings.exists()


def test_settings_invalido_no_se_toca(env):
    env.settings.parent.mkdir(parents=True)
    env.settings.write_text("{ no", encoding="utf-8")
    assert _init_user(env) == 1
    assert env.settings.read_text(encoding="utf-8") == "{ no"


def test_conserva_hooks_ajenos(env):
    env.settings.parent.mkdir(parents=True)
    mio = {"matcher": "startup", "hooks": [{"type": "command", "command": "node mio.mjs"}]}
    env.settings.write_text(json.dumps({"model": "x", "hooks": {"SessionStart": [mio]}}), encoding="utf-8")
    _init_user(env)
    data = json.loads(env.settings.read_text(encoding="utf-8"))
    assert data["model"] == "x" and mio in data["hooks"]["SessionStart"]
    assert len(data["hooks"]["SessionStart"]) == 2


def test_no_escribe_en_el_repo(env):
    _init_user(env)
    assert list(env.repo.iterdir()) == []


def test_otro_cliente_no_soportado(env):
    assert _init_user(env, client="cursor") == 2
    assert env.calls == [] and not env.settings.exists()


def test_no_hook_omite_los_dos(env):
    assert _init_user(env, no_hook=True) == 0
    assert env.calls and not env.settings.exists()


def test_desde_cache_uv_registra_pero_no_instala_hooks(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "executable", UV_CACHE_PY)
    monkeypatch.setattr(cli, "_uv_cache_dir", lambda: None)
    assert _init_user(env) == 0
    assert env.calls and not env.settings.exists()
    assert "uv tool install leo-mcp" in capsys.readouterr().out


def test_main_acepta_el_flag(env):
    assert cli.main(["init", "--user"]) == 0
    assert env.settings.exists()


def _doctor(e, monkeypatch, capsys):
    from leo_code import engine
    monkeypatch.setattr(engine, "_WATCH", False)   # sin observer de FS en el test
    capsys.readouterr()
    cli.cmd_doctor(Namespace(repo=str(e.repo)))
    return capsys.readouterr().out


def test_doctor_ve_los_hooks_de_usuario(env, monkeypatch, capsys):
    _init_user(env)
    out = _doctor(env, monkeypatch, capsys)
    assert "[ok ] guard hook" in out and "[ok ] index hook" in out


def test_doctor_sin_index_hook_lo_sugiere(env, monkeypatch, capsys):
    out = _doctor(env, monkeypatch, capsys)
    assert "index hook" in out and "leo-mcp init --user" in out


def test_doctor_respeta_la_escotilla_del_indice(env, monkeypatch, capsys):
    _init_user(env)
    monkeypatch.setenv("LEO_INDEX_HOOK", "0")
    assert "off (LEO_INDEX_HOOK=0)" in _doctor(env, monkeypatch, capsys)
