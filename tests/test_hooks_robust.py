"""Revisión #15 (16/11): los hooks nunca bloquean y leen bien lo que manda Claude Code.

Claude Code manda el JSON del hook en UTF-8. En Windows Python lee stdin como cp1252: una
ruta con tilde (`C:\\Users\\León\\…`) llegaba deformada y los dos hooks se callaban siempre.
Y en Claude Code un exit 2 BLOQUEA la edición: `except Exception` no atrapa SystemExit."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from leo_code import engine, guard_hook, index_hook

ROOT = Path(__file__).resolve().parents[1]


def _fake_stdin(monkeypatch, payload: dict):
    """stdin como lo ve Python en Windows: bytes UTF-8 tras un lector cp1252."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252"))


def test_guard_hook_lee_utf8_aunque_la_consola_sea_cp1252(tmp_path, monkeypatch):
    root = tmp_path / "Le\u00f3n" / "app"
    root.mkdir(parents=True)
    (root / "core.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return f()\n",
                                  encoding="utf-8")
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    for k, v in (("_indexer", None), ("_structural_at", {}), ("_generation", {}),
                 ("_synced_at", {}), ("_save_timers", {}), ("_SAVE_DEBOUNCE_S", 0.0),
                 ("_WATCH", False)):
        monkeypatch.setattr(engine, k, v)
    engine.ensure_structural(str(root))
    engine._get_indexer().stop_watch()
    payload = {"tool_name": "Edit", "cwd": str(root),
               "tool_input": {"file_path": str(root / "core.py"), "old_string": "    return 1"}}
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="cp1252",   # la consola de Windows
               LEO_CACHE_DIR=str(tmp_path / "cache"), LEO_WATCH="0")
    p = subprocess.run([sys.executable, "-m", "leo_code.guard_hook"],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env=env, timeout=120)
    assert p.returncode == 0
    assert p.stdout, p.stderr.decode("utf-8", "replace")[-300:]
    assert "g" in json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]


def test_index_hook_lee_utf8_aunque_la_consola_sea_cp1252(tmp_path, monkeypatch):
    repo = tmp_path / "Le\u00f3n"
    (repo / ".git").mkdir(parents=True)
    spawned = []
    monkeypatch.setattr(index_hook, "_spawn", spawned.append)
    monkeypatch.delenv("LEO_INDEX_HOOK", raising=False)
    _fake_stdin(monkeypatch, {"cwd": str(repo)})
    assert index_hook.main() == 0
    assert spawned and spawned[0][-1] == str(repo)


@pytest.mark.parametrize("hook", [guard_hook, index_hook])
@pytest.mark.parametrize("exc", [SystemExit(2), KeyboardInterrupt()])
def test_ninguna_excepcion_sale_con_codigo_distinto_de_cero(hook, exc, monkeypatch):
    """exit 2 bloquea la edición en Claude Code: ni un SystemExit(2) de dentro puede salir."""
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(hook, "run", boom)
    monkeypatch.delenv("LEO_GUARD_HOOK", raising=False)
    _fake_stdin(monkeypatch, {"tool_name": "Edit"})
    assert hook.main() == 0
