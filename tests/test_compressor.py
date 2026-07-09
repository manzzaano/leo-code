"""Tests: compressor — estrategias de compresión."""

from leo_code.core.parser import Capsule
from leo_code.rag.compressor import compress


def _make_capsule(name, ctype="function", calls=None, content="", docstring="",
                  file_path="test.py", signature="", language="python", properties=None):
    sig = signature or f"def {name}() -> None"
    return Capsule(
        id=name, type=ctype, name=name, file_path=file_path,
        start_line=1, end_line=3, language=language,
        signature=sig, content=content or f"def {name}(): pass",
        docstring=docstring, calls=calls or [],
        properties=properties if properties is not None else
            {"parametros": "", "tipo_retorno": "None", "lineas": 3, "module": "test"},
    )


def test_compress_code_query():
    caps = [
        _make_capsule("foo", content="def foo():\n    return 1", docstring="Returns 1"),
        _make_capsule("bar", docstring="Returns 2"),
    ]
    result = compress(caps, caps, task_type="code_query", budget_tokens=1500)
    assert "foo" in result
    assert "bar" in result


def test_compress_search():
    caps = [
        _make_capsule("foo", docstring="Doc"),
        _make_capsule("bar"),  # sin docstring
    ]
    result = compress(caps, caps, task_type="search", budget_tokens=500)
    assert "✗doc" in result or "sin docstring" in result.lower()


def test_compress_refactor():
    target = _make_capsule("target", calls=["helper"])
    helper = _make_capsule("helper")
    caller = _make_capsule("caller", calls=["target"])
    all_caps = [target, helper, caller]
    result = compress([target], all_caps, task_type="refactor")
    assert "target" in result


def test_compress_debug():
    target = _make_capsule("buggy", content="def buggy():\n    return 1/0", docstring="Bug")
    helper = _make_capsule("helper", calls=[])
    result = compress([target], [target, helper], task_type="debug")
    assert "buggy" in result


def test_compress_no_code():
    doc = _make_capsule("terms", ctype="document", content="Terms of service...")
    result = compress([doc], [doc], task_type="no_code")
    assert "terms" in result.lower()


def test_compress_empty():
    result = compress([], [], task_type="code_query")
    assert result == ""


def test_compress_onboard():
    ep = _make_capsule("main", ctype="entrypoint", file_path="main.py",
                       content="if __name__ == '__main__'")
    hdr = _make_capsule("app.__header__", ctype="file_header", file_path="app.py")
    result = compress([], [ep, hdr], task_type="onboard")
    assert len(result) > 0


def test_compress_code_gen():
    caps = [
        _make_capsule("foo", content="def foo():\n    secret_body_marker()", file_path="a/foo.py"),
        _make_capsule("bar", content="def bar():\n    secret_body_marker()", file_path="b/bar.py"),
    ]
    result = compress(caps, caps, task_type="code_gen")
    assert "Estructura del repositorio" in result
    assert "a/foo.py" in result
    assert "b/bar.py" in result
    # code_gen es solo estructura — el cuerpo de las capsulas NUNCA debe aparecer
    # (si alguien "ayuda" agregando el body, esto lo detecta).
    assert "secret_body_marker" not in result


def test_compress_optimize():
    caps = [_make_capsule(f"fn{i}", content=f"def fn{i}(): pass") for i in range(7)]
    result = compress(caps, caps, task_type="optimize")
    assert "Optimiza este codigo" in result
    # Cap duro de 5 items (compressor.py: `if len(nodes) >= 5: break`).
    assert result.count("## ") <= 5
    assert "fn5" not in result
    assert "fn6" not in result


def test_compress_design_review():
    img = _make_capsule("hero", ctype="image", file_path="assets/hero.png",
                         properties={"mime": "image/png", "size_bytes": 1234})
    html = _make_capsule("index_header", ctype="file_header", file_path="index.html",
                          language="html")
    result = compress([], [img, html], task_type="design_review")
    assert "imagen" in result.lower()
    assert "index.html" in result


def test_compress_test_gen():
    target = _make_capsule("target_func", calls=["helper"])
    test_cap = _make_capsule("test_target_func", content="def test_target_func(): assert True")
    result = compress([target], [target, test_cap], task_type="test_gen")
    assert "Genera tests" in result
    assert "target_func" in result
    assert "tests existentes en el repo" in result
    assert "test_target_func" in result

    # test_gen esta exento del short-circuit "sin target -> vacio" (compressor.py:129):
    # sin target, debe seguir devolviendo los tests existentes como referencia.
    result_no_target = compress([], [test_cap], task_type="test_gen")
    assert "test_target_func" in result_no_target


def test_compress_review():
    caps = [_make_capsule(f"item{i}", calls=["helper"]) for i in range(13)]
    result = compress(caps, caps, task_type="review")
    assert "Revisa este codigo" in result
    # max_items=10 en COMPRESS_STRATEGIES["review"] — cap real, no solo "no vacio".
    assert result.count("## ") == 10


def test_compress_audit():
    target = _make_capsule("handler", calls=["db_query"])
    result = compress([target], [target], task_type="audit")
    assert "SQL injection" in result
    assert "handler" in result
