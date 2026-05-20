"""Tests: compressor — estrategias de compresión."""

from leo_code.core.parser import Capsule
from leo_code.rag.compressor import compress


def _make_capsule(name, ctype="function", calls=None, content="", docstring="",
                  file_path="test.py", signature=""):
    sig = signature or f"def {name}() -> None"
    return Capsule(
        id=name, type=ctype, name=name, file_path=file_path,
        start_line=1, end_line=3, language="python",
        signature=sig, content=content or f"def {name}(): pass",
        docstring=docstring, calls=calls or [],
        properties={"parametros": "", "tipo_retorno": "None", "lineas": 3, "module": "test"},
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
