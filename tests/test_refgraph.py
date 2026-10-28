"""Regression: las aristas de referencia capturan dispatch indirecto (dict/módulo)
sin inyectar ruido de nombres comunes. augment_refs lee los archivos reales del repo
(el indexer siempre indexa archivos de disco), así que los tests usan archivos temp."""

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
