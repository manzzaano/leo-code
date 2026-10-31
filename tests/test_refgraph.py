"""Regression: las aristas de referencia capturan dispatch indirecto (dict/módulo)
sin inyectar ruido de nombres comunes. augment_refs lee los archivos reales del repo
(el indexer siempre indexa archivos de disco), así que los tests usan archivos temp."""

import ast

from leo_code.core.parser import extract_from_python
from leo_code.core.refgraph import augment_refs


def _caps_from(path, src):
    path.write_text(src, encoding="utf-8")
    return {c.id: c for c in extract_from_python(src, str(path))}


def test_module_dispatch_edge(tmp_path):
    src = (
        "def _detect_go(x):\n    return x\n\n"
        "DISPATCH = {'go': _detect_go}\n\n"
        "def detect(lang, x):\n    return DISPATCH[lang](x)\n"
    )
    caps = _caps_from(tmp_path / "m.py", src)
    augment_refs(caps)
    detect = next(c for c in caps.values() if c.name == "detect")
    table = next(c for c in caps.values() if c.name == "DISPATCH")
    # la tabla es un nodo: detect → DISPATCH → _detect_go
    assert "DISPATCH" in detect.calls and "_detect_go" in table.calls


def test_unique_only_no_common_name_noise(tmp_path):
    # 'run' definido 2 veces → NO debe inyectarse por referencia (preserva precisión)
    src = ("def run():\n pass\n\nclass A:\n def run(self):\n  pass\n\n"
           "RUN = run\n\ndef caller():\n pass\n")
    caps = _caps_from(tmp_path / "m.py", src)
    augment_refs(caps)
    caller = next(c for c in caps.values() if c.name == "caller")
    assert "run" not in caller.calls   # nombre no único → sin arista de referencia


def test_main_block_reaches_functions_of_its_file(tmp_path):
    # Una función que relanza su archivo como script (`subprocess … __file__`) depende de lo
    # que hace el bloque __main__: audit_formal.check_f → --mem-child → compute_context.
    src = ("def child():\n    return 1\n\n"
           "def spawn():\n    return run_script(__file__)\n\n"
           "if __name__ == '__main__':\n    child()\n")
    caps = _caps_from(tmp_path / "m.py", src)
    augment_refs(caps)
    spawn = next(c for c in caps.values() if c.name == "spawn")
    assert "child" in spawn.calls


_REFS_SRC = (
    "import os\n\n"
    "def deco(f):\n    return f\n\n"
    "def target():\n    return 1\n\n"
    "def other():\n    return 2\n\n"
    "TABLE = {'t': target}\n\n"
    "@deco\ndef decorated():\n    return TABLE\n\n"
    "@deco\nclass K:\n    attr = other\n\n"
    "    @deco\n    def m(self):\n        return self.helper_attr + other()\n\n"
    "def helper_attr():\n    return os.sep\n\n"
    "if __name__ == '__main__':\n    decorated()\n"
)


def test_refs_stored_at_parse_match_parsing_the_content(tmp_path):
    stored = _caps_from(tmp_path / "m.py", _REFS_SRC)
    assert any("refs" in c.properties for c in stored.values())
    reparsed = _caps_from(tmp_path / "m.py", _REFS_SRC)
    for c in reparsed.values():
        c.properties.pop("refs", None)
    augment_refs(stored)
    augment_refs(reparsed)
    assert {k: set(c.calls) for k, c in stored.items()} == {k: set(c.calls) for k, c in reparsed.items()}


def test_stored_refs_avoid_reparsing(tmp_path, monkeypatch):
    caps = _caps_from(tmp_path / "m.py", _REFS_SRC)
    parsed = []
    real = ast.parse
    monkeypatch.setattr(ast, "parse", lambda s, *a, **k: parsed.append(s) or real(s, *a, **k))
    augment_refs(caps)
    decorated = next(c for c in caps.values() if c.name == "decorated")
    assert "TABLE" in decorated.calls
    assert "deco" not in decorated.calls            # el decorador no es parte del cuerpo
    assert decorated.content not in parsed


def test_capsules_without_stored_refs_are_parsed(tmp_path):
    # El parser TS y el genérico no guardan refs
    caps = _caps_from(tmp_path / "m.py", _REFS_SRC)
    table = next(c for c in caps.values() if c.name == "TABLE")
    del table.properties["refs"]
    augment_refs(caps)
    assert "target" in table.calls
