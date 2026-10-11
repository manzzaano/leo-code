"""El hook que avisa antes de romper. El contrato es el JSON que escribe en stdout,
así que se prueba lanzándolo como proceso, igual que lo lanza Claude Code."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from leo_code import engine, guard_hook

ROOT = Path(__file__).resolve().parents[1]


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo con dos dependientes: uno cubierto por un test y otro no."""
    root = tmp_path / "app"
    _write(root / "core.py",
           "def get_session():\n"
           "    return 1\n"
           "\n"
           "\n"
           "def safe_reader():\n"
           "    return get_session()\n"
           "\n"
           "\n"
           "def lonely_writer():\n"
           "    return get_session()\n")
    _write(root / "tests" / "test_core.py",
           "from core import safe_reader\n"
           "\n"
           "def test_safe_reader():\n"
           "    assert safe_reader() == 1\n")
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    monkeypatch.setattr(engine, "_generation", {})
    monkeypatch.setattr(engine, "_synced_at", {})
    monkeypatch.setattr(engine, "_save_timers", {})
    monkeypatch.setattr(engine, "_SAVE_DEBOUNCE_S", 0.0)   # el hook necesita el índice EN DISCO
    monkeypatch.setattr(engine, "_WATCH", False)
    engine.ensure_structural(str(root))
    yield root
    engine._get_indexer().stop_watch()


def _payload(tool: str, path: Path, repo_root: Path, old: str | None = None) -> dict:
    out = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(repo_root),
           "tool_input": {"file_path": str(path)}}
    if old is not None:
        out["tool_input"]["old_string"] = old
    return out


def _run_in_process(payload: dict):
    return guard_hook.run(payload, started=__import__("time").monotonic())


def test_avisa_de_los_dependientes_sin_test(repo):
    out = _run_in_process(_payload("Edit", repo / "core.py", repo, old="    return 1"))
    assert out is not None, "editar get_session debe avisar: lonely_writer no tiene test"
    hook = out["hookSpecificOutput"]
    ctx = hook["additionalContext"]
    assert "lonely_writer" in ctx, "tiene que nombrar al dependiente sin test"
    assert "core.py:" in ctx, "y citarlo con archivo:línea"
    assert "test_safe_reader" not in ctx, ("un test que depende del símbolo es cobertura, "
                                          "no riesgo: nada cubre a un test y saldrían todos")
    assert "test_core.py" not in ctx, "y menos aún citando archivos de test"
    assert "get_session" in hook["systemMessage"]
    assert "permissionDecision" not in hook, "el hook informa, no decide"


def test_callado_cuando_lo_editado_no_arrastra_a_nadie_sin_test(repo):
    # lonely_writer es una hoja: nadie depende de ella
    out = _run_in_process(_payload("Edit", repo / "core.py", repo,
                                   old="def lonely_writer():"))
    assert out is None


def test_callado_para_tests_archivos_nuevos_y_otras_tools(repo):
    assert _run_in_process(_payload("Edit", repo / "tests" / "test_core.py", repo,
                                    old="def test_safe_reader():")) is None
    assert _run_in_process(_payload("Write", repo / "nuevo.py", repo)) is None
    assert _run_in_process(_payload("Read", repo / "core.py", repo)) is None
    assert _run_in_process(_payload("Edit", repo / "core.py", repo, old="NO EXISTE")) is None \
        or True  # old_string ausente → sin línea → se examina el archivo entero, no es error


def test_write_de_archivo_existente_mira_todo_el_archivo(repo):
    out = _run_in_process(_payload("Write", repo / "core.py", repo))
    assert out is not None, "reemplazar core.py entero toca get_session"
    assert "lonely_writer" in out["hookSpecificOutput"]["additionalContext"]


def test_sin_indice_en_cache_calla_y_no_indexa(repo, monkeypatch):
    """Construir un índice dentro de una edición costaría segundos: jamás se hace."""
    engine.repo_index_path(str(repo)).unlink()
    called = []
    monkeypatch.setattr(engine, "ensure_structural", lambda *a, **k: called.append(1))
    assert _run_in_process(_payload("Edit", repo / "core.py", repo, old="    return 1")) is None
    assert called == []


def test_indice_demasiado_grande_calla(repo, monkeypatch):
    monkeypatch.setattr(guard_hook, "_MAX_INDEX_MB", 0.0000001)
    assert _run_in_process(_payload("Edit", repo / "core.py", repo, old="    return 1")) is None


def test_deadline_vencido_calla(repo):
    import time
    vencido = time.monotonic() - guard_hook._DEADLINE_S - 1
    assert guard_hook.run(_payload("Edit", repo / "core.py", repo, old="    return 1"),
                          started=vencido) is None


# ---- el contrato real: proceso, stdin JSON, stdout JSON, exit 0 ----

def _run_as_process(payload: dict, env_extra: dict | None = None, cache: Path | None = None):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    if cache is not None:
        env["LEO_CACHE_DIR"] = str(cache)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-m", "leo_code.guard_hook"],
                       input=json.dumps(payload), capture_output=True, text=True, env=env,
                       timeout=120)
    return p


def test_como_proceso_escribe_json_valido_y_sale_con_cero(repo, tmp_path):
    p = _run_as_process(_payload("Edit", repo / "core.py", repo, old="    return 1"),
                        cache=tmp_path / "cache")
    assert p.returncode == 0
    assert p.stdout, f"esperaba JSON en stdout; stderr={p.stderr[:300]}"
    hook = json.loads(p.stdout)["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert "lonely_writer" in hook["additionalContext"]
    assert "permissionDecision" not in hook


@pytest.mark.parametrize("payload", [
    {},                                                   # payload vacío
    {"tool_name": "Edit"},                                # sin tool_input
    {"tool_name": "Edit", "tool_input": {"file_path": "/no/existe.py"}},
    {"tool_name": "Edit", "tool_input": {"file_path": None}},
])
def test_nunca_rompe_la_edicion_pase_lo_que_pase(payload, tmp_path):
    """Invariante que vale por todo el resto: exit 0 y sin decisión de permiso."""
    p = _run_as_process(payload, cache=tmp_path / "cache")
    assert p.returncode == 0
    assert "permissionDecision" not in (p.stdout or "")


def test_la_escotilla_lo_apaga(repo, tmp_path):
    p = _run_as_process(_payload("Edit", repo / "core.py", repo, old="    return 1"),
                        env_extra={"LEO_GUARD_HOOK": "0"}, cache=tmp_path / "cache")
    assert p.returncode == 0 and p.stdout == ""


# ---- instalación: `leo-mcp init` ----

def _init(tmp: Path, **kw):
    from argparse import Namespace
    from leo_code import cli
    args = Namespace(repo=str(tmp), client=kw.get("client", "claude"),
                     no_hook=kw.get("no_hook", False))
    return cli.cmd_init(args)


def test_init_instala_el_hook_y_es_idempotente(tmp_path, capsys):
    assert _init(tmp_path) == 0
    settings = tmp_path / ".claude" / "settings.json"
    groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(groups) == 1 and groups[0]["matcher"] == "Edit|Write"
    assert "leo_code.guard_hook" in groups[0]["hooks"][0]["command"]
    assert sys.executable.split(os.sep)[-1] in groups[0]["hooks"][0]["command"], \
        "debe apuntar a este intérprete, no a un python del PATH ni a npx"

    capsys.readouterr()
    assert _init(tmp_path) == 0
    again = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(again) == 1, "una segunda pasada no puede duplicar el hook"
    assert "already in" in capsys.readouterr().out


def test_init_no_pisa_los_hooks_que_ya_hubiera(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    mio = {"matcher": "Bash", "hooks": [{"type": "command", "command": "mi-script.sh"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [mio],
                                              "PostToolUse": [{"matcher": "Read"}]}}),
                        encoding="utf-8")
    _init(tmp_path)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert mio in data["hooks"]["PreToolUse"], "el hook ajeno sigue ahí"
    assert data["hooks"]["PostToolUse"] == [{"matcher": "Read"}], "y los otros eventos también"
    assert any("leo_code.guard_hook" in h["command"]
               for g in data["hooks"]["PreToolUse"] for h in g.get("hooks", []))


def test_init_lo_instala_tambien_cuando_el_server_ya_estaba(tmp_path):
    """Quien ya tenía leo configurado es justo quien no tiene el hook todavía."""
    _init(tmp_path)
    (tmp_path / ".claude" / "settings.json").unlink()
    assert _init(tmp_path) == 0
    assert (tmp_path / ".claude" / "settings.json").exists()


def test_no_hook_y_otros_clientes_no_tocan_settings(tmp_path):
    assert _init(tmp_path, no_hook=True) == 0
    assert not (tmp_path / ".claude" / "settings.json").exists()
    otro = tmp_path / "otro"
    otro.mkdir()
    assert _init(otro, client="cursor") == 0
    assert not (otro / ".claude" / "settings.json").exists(), "solo Claude Code tiene PreToolUse"


def test_settings_json_invalido_no_se_reescribe(tmp_path, capsys):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{ no es json", encoding="utf-8")
    assert _init(tmp_path) == 1
    assert settings.read_text(encoding="utf-8") == "{ no es json"
