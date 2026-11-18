"""#18: indexado incremental. A: no reconstruir si el índice ya está en memoria.
B: sync guiado por las rutas que vio el watcher. C: cambios con mtime antiguo."""

import os
import time

import pytest

from leo_code import engine
from leo_code.rag.indexer import Indexer


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def eng(tmp_path_factory, monkeypatch):
    # Caché FUERA del repo: dentro, crear su carpeta es un evento que fuerza walk.
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path_factory.mktemp("cache"))
    monkeypatch.setattr(engine, "_indexer", None)
    monkeypatch.setattr(engine, "_structural_at", {})
    monkeypatch.setattr(engine, "_synced_at", {})
    monkeypatch.setattr(engine, "_generation", {})
    monkeypatch.setattr(engine, "_save_timers", {})
    monkeypatch.setattr(engine, "_RESYNC_S", 0.0)
    yield engine
    for t, _ in list(engine._save_timers.values()):
        t.cancel()
    if engine._indexer is not None:
        engine._indexer.stop_watch()


def _names(repo_str):
    return {c.name for c in engine._repo_caps(engine._get_indexer(), repo_str)}


def _until(fn, timeout=5.0):
    """Los eventos de FS son asíncronos: repite hasta que `fn` devuelva algo."""
    deadline = time.monotonic() + timeout
    out = fn()
    while out is None and time.monotonic() < deadline:
        time.sleep(0.05)
        out = fn()
    return out


# ── A ──────────────────────────────────────────────────────────────────────────

def test_sin_indice_en_disco_una_edicion_no_reconstruye(repo, eng, monkeypatch):
    """La escritura del índice va diferida: mientras no llega a disco, una edición
    reconstruía el repo entero (19 s en django) en vez de sincronizar lo cambiado."""
    monkeypatch.setattr(eng, "_SAVE_DEBOUNCE_S", 3600.0)  # el índice no llega a disco
    monkeypatch.setattr(eng, "_WATCH", False)
    r = os.path.abspath(str(repo))
    assert eng.ensure_structural(r)["action"] == "build"
    assert not eng.repo_index_path(r).exists()

    builds = []
    idx = eng._get_indexer()
    real_build = idx.build
    monkeypatch.setattr(idx, "build", lambda *a, **k: (builds.append(1), real_build(*a, **k))[1])
    time.sleep(0.05)
    (repo / "a.py").write_text("def a():\n    return 1\n\ndef nueva():\n    pass\n", encoding="utf-8")
    os.utime(repo / "a.py", (time.time() + 5, time.time() + 5))

    out = eng.ensure_structural(r)
    assert out is not None and out["action"] == "sync"
    assert builds == []
    assert "nueva" in _names(r)


# ── B ──────────────────────────────────────────────────────────────────────────

watchdog = pytest.importorskip("watchdog")


def _setup_watch(repo, eng, monkeypatch):
    r = os.path.abspath(str(repo))
    eng.ensure_structural(r)
    idx = eng._get_indexer()
    time.sleep(0.6)
    idx.take_changes(r)   # drenar eventos del build
    walks = []
    real = idx._discover_files
    monkeypatch.setattr(idx, "_discover_files", lambda *a, **k: (walks.append(1), real(*a, **k))[1])
    return r, idx, walks


def test_editar_archivo_indexado_no_recorre_el_repo(repo, eng, monkeypatch):
    r, idx, walks = _setup_watch(repo, eng, monkeypatch)
    (repo / "a.py").write_text("def a():\n    return 1\n\ndef nueva():\n    pass\n", encoding="utf-8")
    out = _until(lambda: eng.ensure_structural(r))
    assert out is not None and "nueva" in _names(r)
    assert walks == [], "un archivo ya indexado se re-parsea sin recorrer el repo"


def test_borrar_archivo_indexado_no_recorre_el_repo(repo, eng, monkeypatch):
    r, idx, walks = _setup_watch(repo, eng, monkeypatch)
    (repo / "src" / "b.py").unlink()
    out = _until(lambda: eng.ensure_structural(r))
    assert out is not None and "b" not in _names(r)
    assert walks == []


def test_archivo_nuevo_recorre_el_repo(repo, eng, monkeypatch):
    """Un archivo nuevo pasa por los filtros del walk (.gitignore, minificados)."""
    r, idx, walks = _setup_watch(repo, eng, monkeypatch)
    (repo / "src" / "c.py").write_text("def c():\n    pass\n", encoding="utf-8")
    out = _until(lambda: eng.ensure_structural(r))
    assert out is not None and "c" in _names(r)
    assert walks


def test_renombrar_carpeta_recorre_el_repo(repo, eng, monkeypatch):
    """Un evento de carpeta no dice qué archivos contiene: walk completo."""
    r, idx, walks = _setup_watch(repo, eng, monkeypatch)
    os.rename(repo / "src", repo / "lib")
    out = _until(lambda: eng.ensure_structural(r))
    assert out is not None
    paths = {c.file_path for c in eng._repo_caps(idx, r) if c.name == "b"}
    assert paths == {str(repo / "lib" / "b.py")}
    assert walks


def test_take_changes_devuelve_las_rutas(repo):
    idx = Indexer(hygiene=True)
    r = os.path.abspath(str(repo))
    try:
        idx.build(r)
        assert idx.watch(r)
        time.sleep(0.6)
        idx.take_changes(r)   # drenar eventos del build
        assert idx.take_changes(r) == (False, set())
        (repo / "a.py").write_text("def a():\n    return 5\n", encoding="utf-8")
        dirty, paths = _until(lambda: idx.take_changes(r) if idx._dirty_paths.get(r) else None)
        assert dirty and paths == {str(repo / "a.py")}
    finally:
        idx.stop_watch()


# ── C ──────────────────────────────────────────────────────────────────────────

def _replace_keep_old_mtime(path, body):
    """Como `cp -p`, rsync -a o tar: contenido nuevo, mtime antiguo."""
    old = path.stat().st_mtime - 100
    path.write_text(body, encoding="utf-8")
    os.utime(path, (old, old))


def test_contenido_nuevo_con_mtime_antiguo_se_detecta(repo):
    idx = Indexer(hygiene=True)
    r = os.path.abspath(str(repo))
    idx.build(r)
    since = time.time()
    _replace_keep_old_mtime(repo / "src" / "b.py", "def gamma():\n    pass\n")
    stats = idx.sync(r, since_mtime=since)
    names = {c.name for c in idx.get_capsules().values()}
    assert "gamma" in names and "b" not in names
    assert stats["changed"] == 1


def test_mismo_contenido_con_otro_mtime_no_se_reparsea(repo):
    idx = Indexer(hygiene=True)
    r = os.path.abspath(str(repo))
    idx.build(r)
    since = time.time()
    st = (repo / "a.py").stat()
    os.utime(repo / "a.py", (st.st_mtime - 50, st.st_mtime - 50))
    assert idx.sync(r, since_mtime=since)["changed"] == 0


def test_la_huella_por_archivo_sobrevive_a_guardar_y_cargar(repo, tmp_path):
    """Entre sesiones: el índice cargado de disco debe ver el cambio con mtime antiguo."""
    r = os.path.abspath(str(repo))
    idx = Indexer(hygiene=True)
    idx.build(r)
    path = tmp_path / "idx.json.gz"
    idx.save(str(path), repo=r)
    since = time.time()
    _replace_keep_old_mtime(repo / "src" / "b.py", "def gamma():\n    pass\n")

    idx2 = Indexer(hygiene=True)
    idx2.load(str(path))
    idx2.sync(r, since_mtime=since)
    names = {c.name for c in idx2.get_capsules().values()}
    assert "gamma" in names and "b" not in names


def test_mover_carpeta_fuera_del_repo_quita_sus_simbolos(repo, eng, monkeypatch, tmp_path_factory):
    """En Windows, una carpeta que sale del árbol (papelera, mv a otro sitio) llega como
    FileDeletedEvent de la carpeta, sin eventos de sus archivos: tiene que haber walk."""
    import shutil
    r, idx, walks = _setup_watch(repo, eng, monkeypatch)
    shutil.move(str(repo / "src"), str(tmp_path_factory.mktemp("fuera") / "src"))
    out = _until(lambda: eng.ensure_structural(r))
    assert out is not None and "b" not in _names(r)
