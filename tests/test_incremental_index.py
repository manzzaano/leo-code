"""Tests: indexado incremental (sync) — re-parsea solo lo cambiado/nuevo/borrado."""

import time
from pathlib import Path

from leo_code.rag.indexer import Indexer


def _write(p: Path, body: str):
    p.write_text(body, encoding="utf-8")


def test_sync_reparses_only_changed(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    _write(a, "def foo():\n    return 1\n")
    _write(b, "def bar():\n    return 2\n")

    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"])
    names0 = {c.name for c in idx.get_capsules().values()}
    assert {"foo", "bar"} <= names0

    cache_mtime = time.time()
    time.sleep(0.01)
    # cambia solo a.py: foo -> foo2
    _write(a, "def foo2():\n    return 9\n")

    stats = idx.sync(str(tmp_path), since_mtime=cache_mtime, languages=["python"])
    assert stats["changed"] == 1          # solo a.py
    names1 = {c.name for c in idx.get_capsules().values()}
    assert "foo2" in names1               # nuevo símbolo de a.py
    assert "foo" not in names1            # viejo de a.py eliminado
    assert "bar" in names1                # b.py intacto


def test_sync_adds_new_and_removes_deleted(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    _write(a, "def foo():\n    return 1\n")
    _write(b, "def bar():\n    return 2\n")
    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"])

    cache_mtime = time.time()
    time.sleep(0.01)
    b.unlink()                            # borra b.py
    _write(tmp_path / "c.py", "def baz():\n    return 3\n")  # nuevo

    stats = idx.sync(str(tmp_path), since_mtime=cache_mtime, languages=["python"])
    names = {c.name for c in idx.get_capsules().values()}
    assert "baz" in names                 # nuevo añadido
    assert "bar" not in names             # borrado eliminado
    assert "foo" in names
    assert stats["new"] == 1 and stats["deleted"] == 1


def test_sync_reresolves_call_graph(tmp_path):
    # caller en a.py llama a helper en b.py → called_by cross-file
    _write(tmp_path / "a.py", "def caller():\n    return helper()\n")
    _write(tmp_path / "b.py", "def helper():\n    return 1\n")
    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"])

    cache_mtime = time.time()
    time.sleep(0.01)
    # caller deja de llamar a helper
    _write(tmp_path / "a.py", "def caller():\n    return 0\n")
    idx.sync(str(tmp_path), since_mtime=cache_mtime, languages=["python"])

    helper = next(c for c in idx.get_capsules().values() if c.name == "helper")
    caller_ids = [c.id for c in idx.get_capsules().values() if c.name == "caller"]
    # tras el sync, helper ya no debe estar llamado por caller (called_by re-resuelto)
    assert not any(cid in helper.called_by for cid in caller_ids)


def test_rebuild_does_not_accumulate_capsules(tmp_path):
    # Bug real observado: build() sobre estado previo apilaba capsulas (4128 vs
    # 1912 esperadas). Un rebuild del mismo repo debe dejar SOLO lo actual.
    a = tmp_path / "a.py"
    _write(a, "def foo():\n    return 1\n")
    idx = Indexer()
    idx.build(str(tmp_path), languages=["python"])
    n1 = len(idx.get_capsules())

    _write(a, "def foo_renamed():\n    return 1\n")
    idx.build(str(tmp_path), languages=["python"])
    names = {c.name for c in idx.get_capsules().values()}
    assert "foo_renamed" in names
    assert "foo" not in names                 # el viejo no sobrevive al rebuild
    assert len(idx.get_capsules()) == n1      # mismo repo -> mismo tamano, sin apilar


def test_rebuild_prunes_dead_absolute_paths_but_keeps_other_repos(tmp_path):
    # Repo movido: capsulas con ruta absoluta inexistente son fantasmas -> fuera.
    # Capsulas de OTRO repo vivo se conservan (Indexer multi-repo).
    repo_a = tmp_path / "repo_a"; repo_a.mkdir()
    repo_b = tmp_path / "repo_b"; repo_b.mkdir()
    _write(repo_a / "a.py", "def in_a():\n    return 1\n")
    _write(repo_b / "b.py", "def in_b():\n    return 2\n")

    idx = Indexer()
    idx.build(str(repo_a), languages=["python"])
    idx.build(str(repo_b), languages=["python"])
    # simula capsula huerfana de un repo que ya no existe en disco
    caps = idx.get_capsules()
    ghost_id = next(iter(caps))
    import copy
    ghost = copy.copy(caps[ghost_id])
    ghost.id = "ghost1"
    ghost.file_path = str(tmp_path / "repo_borrado" / "gone.py")
    caps["ghost1"] = ghost

    idx.build(str(repo_a), languages=["python"])  # rebuild de A
    names = {c.name for c in idx.get_capsules().values()}
    paths = {c.file_path for c in idx.get_capsules().values()}
    assert "in_a" in names and "in_b" in names    # B (otro repo vivo) intacto
    assert not any("repo_borrado" in p for p in paths)  # fantasma podado
