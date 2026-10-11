"""El watcher de FS decide si hay que re-sincronizar: sin cambios, cero walk."""

import os
import time

import pytest

from leo_code.rag.indexer import Indexer

watchdog = pytest.importorskip("watchdog")


def _wait_dirty(idx: Indexer, repo: str, timeout: float = 5.0) -> bool:
    """Los eventos de FS son asíncronos: se espera a que el watcher los vea."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if idx.take_dirty(repo):
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    return tmp_path


def test_watch_detecta_cambios_reales_y_ignora_el_ruido(repo):
    idx = Indexer(hygiene=True)
    try:
        assert idx.watch(str(repo)) is True
        assert idx.watch(str(repo)) is True  # idempotente: un solo observer por repo
        assert idx.take_dirty(str(repo)) is False  # arranca limpio

        # (1) editar un archivo indexable ensucia
        (repo / "a.py").write_text("def a():\n    return 99\n", encoding="utf-8")
        assert _wait_dirty(idx, str(repo)), "una edición .py debe marcar el repo sucio"
        # take_dirty limpia: la siguiente lectura ya no ve nada
        assert idx.take_dirty(str(repo)) is False

        # (2) crear uno nuevo en un subdirectorio también
        (repo / "sub" / "c.py").write_text("def c():\n    return 3\n", encoding="utf-8")
        assert _wait_dirty(idx, str(repo)), "un archivo nuevo debe marcar el repo sucio"

        # (3) ruido que NO se indexa: ni .git ni una extensión desconocida despiertan un sync.
        # Antes hay que drenar: el SO emite varios eventos por escritura (created+modified)
        # y los rezagados del paso (2) ensuciarían de nuevo tras el take_dirty.
        time.sleep(0.6)
        idx.take_dirty(str(repo))
        (repo / ".git").mkdir()
        (repo / ".git" / "index.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "notas.bin").write_bytes(b"\x00\x01")
        time.sleep(0.6)
        assert idx.take_dirty(str(repo)) is False, ".git y extensiones no indexadas no deben ensuciar"
    finally:
        idx.stop_watch()


def test_ensure_structural_no_walkea_si_el_watcher_no_vio_nada(repo, tmp_path, monkeypatch):
    from leo_code import engine

    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    monkeypatch.setattr(engine, "_generation", {})
    monkeypatch.setattr(engine, "_RESYNC_S", 0.0)  # sin watcher, siempre re-walkearía

    repo_str = os.path.abspath(str(repo))
    try:
        first = engine.ensure_structural(repo_str)
        assert first is not None and first["capsules"] >= 2  # build inicial

        idx = engine._get_indexer()
        calls = []
        real_discover = idx._discover_files
        monkeypatch.setattr(idx, "_discover_files",
                            lambda *a, **k: (calls.append(1), real_discover(*a, **k))[1])

        assert engine.ensure_structural(repo_str) is None
        assert calls == [], "sin cambios en disco no debe descubrirse ningún archivo"

        # red de seguridad: pasado _MAX_STALE_S se re-walkea aunque el watcher calle
        # (FS que no entrega eventos)
        monkeypatch.setattr(engine, "_MAX_STALE_S", 0.0)
        engine.ensure_structural(repo_str)
        assert calls, "tras _MAX_STALE_S debe hacerse el walk de seguridad"
        monkeypatch.setattr(engine, "_MAX_STALE_S", 60.0)
        calls.clear()

        (repo / "a.py").write_text("def a():\n    return 1\n\ndef nueva():\n    return a()\n",
                                   encoding="utf-8")
        deadline = time.monotonic() + 5.0
        out = None
        while time.monotonic() < deadline and out is None:
            out = engine.ensure_structural(repo_str)
            if out is None:
                time.sleep(0.05)
        assert out is not None, "tras editar un archivo el sync debe dispararse"
        assert calls, "el sync real sí descubre archivos"
        assert any(c.name == "nueva" for c in engine._repo_caps(idx, repo_str))
    finally:
        engine._get_indexer().stop_watch()


def test_doctor_reporta_el_estado_del_watcher(repo, tmp_path, monkeypatch, capsys):
    """Sin esta fila, un FS que no entrega eventos se ve como "va lento" y nada más."""
    import argparse

    from leo_code import cli, engine

    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    args = argparse.Namespace(repo=str(repo))

    assert cli.cmd_doctor(args) == 0
    assert "watch" in capsys.readouterr().out

    monkeypatch.setattr(engine, "_WATCH", False)
    assert cli.cmd_doctor(args) == 0
    assert "LEO_WATCH=0" in capsys.readouterr().out
