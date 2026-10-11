"""El índice en disco se escribe diferido: reescribirlo entero costaba 3 s a 100k
símbolos y 9 s a 300k, y se pagaba dentro de la llamada al tool tras cada edición."""

import time

import pytest

from leo_code import engine


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    monkeypatch.setattr(engine, "_generation", {})
    monkeypatch.setattr(engine, "_synced_at", {})
    monkeypatch.setattr(engine, "_save_timers", {})
    monkeypatch.setattr(engine, "_RESYNC_S", 0.0)
    monkeypatch.setattr(engine, "_WATCH", False)   # el walk ve el cambio sin esperar eventos
    monkeypatch.setattr(engine, "_SAVE_DEBOUNCE_S", 30.0)  # no debe escribirse durante el test
    yield tmp_path
    engine._get_indexer().stop_watch()


def test_la_llamada_no_espera_a_que_se_escriba_el_indice(repo):
    engine.ensure_structural(str(repo))
    path = engine.repo_index_path(str(repo))
    assert not path.exists(), "el build no debe bloquear la llamada escribiendo el índice"
    assert str(repo) in engine._save_timers, "pero la escritura tiene que quedar agendada"

    engine.flush_index(str(repo))
    assert path.exists(), "flush_index escribe lo pendiente"
    assert not engine._save_timers, "y deja de haber nada agendado"


def test_los_cambios_se_siguen_viendo_sin_haber_escrito_el_indice(repo):
    """La marca de `since_mtime` vive en memoria. Si se leyera del mtime del índice
    —que ahora puede no existir todavía— el sync mediría desde una marca congelada."""
    engine.ensure_structural(str(repo))
    assert not engine.repo_index_path(str(repo)).exists()

    time.sleep(0.05)   # > tick del reloj de Windows (~15,6 ms)
    (repo / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    out = engine.ensure_structural(str(repo))
    assert out is not None, "un archivo nuevo debe verse aunque el índice no esté en disco"
    names = {c.name for c in engine._repo_caps(engine._get_indexer(), str(repo))}
    assert {"a", "b"} <= names

    time.sleep(0.05)
    (repo / "a.py").write_text("def a():\n    return 1\n\ndef tercera():\n    return 3\n",
                               encoding="utf-8")
    assert engine.ensure_structural(str(repo)) is not None, "y la edición siguiente también"
    names = {c.name for c in engine._repo_caps(engine._get_indexer(), str(repo))}
    assert "tercera" in names


def test_el_flush_escribe_donde_se_agendo_no_donde_apunte_la_cache_ahora(repo, monkeypatch, tmp_path):
    """Un flush tardío no debe escribir en una caché que ya se movió (pasaba de verdad:
    al terminar los tests, atexit escribía índices vacíos en la caché real del usuario)."""
    engine.ensure_structural(str(repo))
    agendado = engine.repo_index_path(str(repo))

    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "otra-cache")
    engine.flush_index()

    assert agendado.exists()
    assert not (tmp_path / "otra-cache").exists()


def test_no_se_escribe_cache_de_un_repo_sin_simbolos(repo, monkeypatch):
    """Índices de 0 símbolos solo ensucian la caché."""
    engine.ensure_structural(str(repo))
    idx = engine._get_indexer()
    with engine._index_lock:
        idx._capsules = {}
    engine.flush_index()
    assert not engine.repo_index_path(str(repo)).exists()
