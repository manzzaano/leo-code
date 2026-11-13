"""El recall semántico es opcional: si qdrant falla, get_context sigue sin él."""

from leo_code import engine


class _Broken:
    def __init__(self, **kw):
        pass

    def _boom(self, *a, **k):
        raise ValueError("validation errors for CreateCollection")

    add = search = count = _boom


def test_un_fallo_de_qdrant_apaga_la_semantica_y_no_tumba_la_llamada(monkeypatch, tmp_path, capsys):
    import leo_code.rag.vector_store as vsmod
    monkeypatch.setattr(engine, "SEMANTIC", True)
    monkeypatch.setattr(vsmod, "VectorStore", _Broken)
    monkeypatch.setattr(engine, "_vector_stores", {})
    vs = engine._get_vector_store(str(tmp_path))
    assert vs.count() == 0
    vs.add([])
    assert vs.search("q", top_k=5) == []
    err = capsys.readouterr().err
    assert err.count("semantic recall off") == 1 and "CreateCollection" in err
