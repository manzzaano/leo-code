"""Regression: si otro proceso leo tiene el storage qdrant, VectorStore degrada a
memoria en vez de colgarse para siempre en el file lock (get_context >3 min muerto)."""

import portalocker

from leo_code.rag.vector_store import VectorStore


def test_falls_back_to_memory_when_locked(tmp_path):
    storage = tmp_path / "qdrant"
    storage.mkdir()
    lock = storage / ".lock"
    lock.write_text("")
    with open(lock, "a") as held:
        portalocker.lock(held, portalocker.LOCK_EX | portalocker.LOCK_NB)  # simula otro proceso
        vs = VectorStore(collection_name="t_x", path=str(storage))
        assert vs._storage_locked() is True
        c = vs.client                       # no cuelga: cae a memoria
        assert c is not None
        portalocker.unlock(held)


def test_uses_disk_when_free(tmp_path):
    vs = VectorStore(collection_name="t_y", path=str(tmp_path / "q2"))
    assert vs._storage_locked() is False
    assert vs.client is not None
