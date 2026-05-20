"""Tests: parser — extracción de cápsulas Python."""

from leo_code.core.parser import (
    Capsule, extract_from_python, build_call_graph, detect_language, EXT_LANG
)


def test_extract_function():
    code = """
def greet(name: str) -> str:
    '''Say hello.'''
    return f"Hello {name}"
"""
    caps = extract_from_python(code, "test.py")
    funcs = [c for c in caps if c.type == "function"]
    assert len(funcs) == 1
    f = funcs[0]
    assert f.name == "greet"
    assert f.signature == "def greet(name: str) -> str"
    assert f.docstring == "Say hello."
    assert f.properties["parametros"] == "name: str"
    assert f.properties["tipo_retorno"] == "str"
    assert f.properties["lineas"] == 3


def test_extract_class():
    code = """
class UserService:
    '''Handles users.'''
    def create(self, name: str) -> dict:
        return {"name": name}
"""
    caps = extract_from_python(code, "svc.py")
    classes = [c for c in caps if c.type == "class"]
    assert len(classes) == 1
    c = classes[0]
    assert c.name == "UserService"
    assert c.docstring == "Handles users."
    assert "create" in c.properties["metodos"]


def test_extract_async_function():
    code = """
async def fetch_data(url: str) -> dict:
    '''Fetch from API.'''
    import httpx
    async with httpx.AsyncClient() as c:
        return (await c.get(url)).json()
"""
    caps = extract_from_python(code, "api.py")
    funcs = [c for c in caps if c.type == "async_function"]
    assert len(funcs) == 1
    assert funcs[0].name == "fetch_data"
    assert "async def" in funcs[0].signature


def test_extract_test_function():
    code = """
def test_user_creation():
    assert True
"""
    caps = extract_from_python(code, "test_user.py")
    tests = [c for c in caps if c.type == "test"]
    assert len(tests) == 1
    assert tests[0].name == "test_user_creation"


def test_extract_dataclass():
    code = """
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int
"""
    caps = extract_from_python(code, "models.py")
    dcs = [c for c in caps if c.type == "dataclass"]
    assert len(dcs) == 1
    assert dcs[0].name == "User"
    assert "dataclass" in dcs[0].properties["decorators"]


def test_extract_entrypoint():
    code = """
import sys

if __name__ == "__main__":
    sys.exit(main())
"""
    caps = extract_from_python(code, "main.py")
    eps = [c for c in caps if c.type == "entrypoint"]
    assert len(eps) == 1


def test_extract_call_graph():
    code = """
def b(x):
    return x * 2

def a(x):
    return b(x) + 1
"""
    caps = extract_from_python(code, "calls.py")
    build_call_graph(caps)
    a_caps = [c for c in caps if c.name == "a"][0]
    b_caps = [c for c in caps if c.name == "b"][0]
    assert "b" in a_caps.calls
    assert a_caps.id in b_caps.called_by


def test_extract_empty_file():
    caps = extract_from_python("", "empty.py")
    assert caps == []


def test_detect_language():
    assert detect_language("app.ts") == "typescript"
    assert detect_language("main.go") == "go"
    assert detect_language("lib.rs") == "rust"
    assert detect_language("App.java") == "java"
    assert detect_language("test.rb") == "ruby"
    assert detect_language("index.js") == "javascript"
    assert detect_language("script.py") == "python"
    assert detect_language("file.cpp") == "cpp"
    assert detect_language("Dockerfile") == "text"


def test_ext_lang_coverage():
    assert set(EXT_LANG.values()) >= {
        "python", "javascript", "typescript", "go", "rust", "java", "ruby",
        "c", "cpp", "csharp", "text"
    }


def test_capsule_properties():
    code = """
def complex_fn(a: int, b: str = "x", c: float = 1.0) -> bool:
    '''Doc.'''
    result = helper(a, b)
    return result > c
"""
    caps = extract_from_python(code, "f.py")
    f = [c for c in caps if c.type == "function"][0]
    assert f.properties["lineas"] >= 3
    assert f.properties["module"] == "f.py"
    assert "helper" in f.calls
