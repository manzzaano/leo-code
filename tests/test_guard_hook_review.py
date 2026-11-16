"""Revisión #14 (16/11) del hook de aviso: a quién avisa y cómo lo dice.
Medido en leo-code: avisaba en el 72% de las ediciones (dependientes transitivos), mezclaba
homónimas de otros archivos y citaba rutas absolutas."""

import os
from pathlib import Path

import pytest

from leo_code import engine, guard_hook


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


@pytest.fixture
def index(tmp_path, monkeypatch):
    """Indexa `root` como lo deja la sesión: índice en disco, sin watcher."""
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    for k, v in (("_indexer", None), ("_structural_at", {}), ("_generation", {}),
                 ("_synced_at", {}), ("_save_timers", {}), ("_SAVE_DEBOUNCE_S", 0.0),
                 ("_WATCH", False)):
        monkeypatch.setattr(engine, k, v)
    yield lambda root: engine.ensure_structural(str(root))
    engine._get_indexer().stop_watch()


def _edit(root: Path, file: str, old: str, cwd: Path | None = None):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(cwd or root),
               "tool_input": {"file_path": str(root / file), "old_string": old}}
    import time
    return guard_hook.run(payload, started=time.monotonic())


CORE = ("def get_session():\n    return 1\n\n\n"
        "def safe_reader():\n    return get_session()\n\n\n"
        "def lonely_writer():\n    return get_session()\n")
TEST = "from core import safe_reader\n\ndef test_safe_reader():\n    assert safe_reader() == 1\n"


def test_system_message_va_en_el_nivel_superior(tmp_path, index):
    """A: `systemMessage` es campo universal; dentro de hookSpecificOutput no se muestra."""
    root = tmp_path / "app"
    _write(root / "core.py", CORE); _write(root / "tests" / "test_core.py", TEST)
    index(root)
    out = _edit(root, "core.py", "    return 1")
    assert "get_session" in out["systemMessage"]
    assert "systemMessage" not in out["hookSpecificOutput"]


def test_homonima_de_otro_archivo_no_cuenta(tmp_path, index):
    """B: editar a.run no avisa por los llamadores de b.run."""
    root = tmp_path / "app"
    _write(root / "a.py", "def run():\n    return 1\n")
    _write(root / "b.py", "def run():\n    return 2\n\n\ndef lonely():\n    return run()\n")
    index(root)
    assert _edit(root, "a.py", "    return 1") is None


def test_solo_avisa_por_llamadores_directos_sin_test(tmp_path, index):
    """C: el llamador directo tiene test; que algo más arriba no lo tenga no es aviso."""
    root = tmp_path / "app"
    _write(root / "core.py", "def get_session():\n    return 1\n\n\n"
                             "def mid():\n    return get_session()\n\n\n"
                             "def top():\n    return mid()\n")
    _write(root / "tests" / "test_core.py",
           "from core import mid\n\ndef test_mid():\n    assert mid() == 1\n")
    index(root)
    assert _edit(root, "core.py", "    return 1") is None
    loud = _edit(root, "core.py", "    return get_session()")
    assert loud is not None and "top" in loud["hookSpecificOutput"]["additionalContext"]


def test_cita_rutas_relativas_al_repo(tmp_path, index):
    """D: `core.py:9`, no la ruta absoluta del disco."""
    root = tmp_path / "app"
    _write(root / "core.py", CORE); _write(root / "tests" / "test_core.py", TEST)
    index(root)
    ctx = _edit(root, "core.py", "    return 1")["hookSpecificOutput"]["additionalContext"]
    assert str(tmp_path) not in ctx
    assert "core.py:9" in ctx


@pytest.mark.skipif(os.name != "nt", reason="solo Windows ignora mayúsculas en rutas")
def test_cwd_con_otras_mayusculas_sigue_avisando(tmp_path, index):
    """E: `c:\\users\\…` y `C:\\Users\\…` son la misma carpeta en Windows."""
    root = tmp_path / "app"
    _write(root / "core.py", CORE); _write(root / "tests" / "test_core.py", TEST)
    index(root)
    out = _edit(root, "core.py", "    return 1", cwd=Path(str(root).swapcase()))
    assert out is not None and "lonely_writer" in out["hookSpecificOutput"]["additionalContext"]
