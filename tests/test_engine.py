"""Smoke test: compute_context arma un subgrafo comprimido sin reventar."""

from leo_code.engine import _get_indexer, compute_context


def test_compute_context_finds_named_function(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python"])

    result = compute_context(str(tmp_path), "say_hello", task_type_in="code_query")

    assert "say_hello" in result["context"]
    assert result["capsules_total"] >= 1
    assert result["tokens"] > 0
    assert result["task_type"] == "code_query"


def test_compute_context_no_code_returns_documents(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "notas.txt").write_text(
        "Este modulo explica la arquitectura general del sistema.\n", encoding="utf-8"
    )
    _get_indexer().build(str(tmp_path), languages=["python", "text"])

    result = compute_context(str(tmp_path), "arquitectura", task_type_in="no_code")

    assert result["task_type"] == "no_code"
    assert result["capsules_total"] >= 1
    assert "arquitectura" in result["context"].lower()


def test_la_ruta_de_fuera_del_repo_no_casa_con_la_pregunta(tmp_path):
    # La búsqueda por ruta miraba la ruta ABSOLUTA: con el repo bajo C:/Users/…/AppData,
    # «where is user data stored» casaba con todas las cápsulas por la carpeta padre.
    repo = tmp_path / "userdata" / "proj"
    repo.mkdir(parents=True)
    (repo / "store.py").write_text("def store_record(rec):\n    return rec\n", encoding="utf-8")
    (repo / "misc.py").write_text(
        "".join(f"def unrelated_{i}():\n    return {i}\n\n" for i in range(20)), encoding="utf-8")
    _get_indexer().build(str(repo), languages=["python"])

    ctx = compute_context(str(repo), "where is user data stored", task_type_in="code_query")["context"]

    assert "unrelated_" not in ctx, ctx
