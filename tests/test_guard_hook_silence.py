"""Revisión #16 (17/11): cuándo calla el hook, y que calle por la razón buena.
Medido: tests de Go/JSX/Ruby/Java tomados por producto (en Go nada quedaba cubierto), índice
viejo que culpaba al símbolo equivocado, y 5,8 s por edición con django pese al plazo de 2 s."""

import os
import time
from pathlib import Path

import pytest

from leo_code import engine, guard_hook
from leo_code.guard_hook import _is_test_path


@pytest.mark.parametrize("path", [
    "pkg/foo_test.go", "src/App.test.jsx", "src/App.spec.jsx", "lib/x.test.mjs",
    "lib/x.spec.cjs", "conftest.py", "app/conftest.py", "foo_spec.rb", "foo_test.rb",
    "src/main/FooTest.java", "FooTests.java",
])
def test_reconoce_tests_de_otros_lenguajes(path):
    assert _is_test_path(Path(path))


@pytest.mark.parametrize("path", ["src/Latest.java", "contest.py", "src/latest.go", "spec_utils.rb"])
def test_no_confunde_producto_con_test(path):
    assert not _is_test_path(Path(path))


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_CACHE_DIR", tmp_path / "cache")
    for k, v in (("_indexer", None), ("_structural_at", {}), ("_generation", {}),
                 ("_synced_at", {}), ("_save_timers", {}), ("_SAVE_DEBOUNCE_S", 0.0),
                 ("_WATCH", False)):
        monkeypatch.setattr(engine, k, v)
    yield lambda root: engine.ensure_structural(str(root))
    engine._get_indexer().stop_watch()


def _edit(root: Path, file: str, old: str, started: float | None = None):
    payload = {"tool_name": "Edit", "cwd": str(root),
               "tool_input": {"file_path": str(root / file), "old_string": old}}
    return guard_hook.run(payload, started=time.monotonic() if started is None else started)


def test_go_un_test_de_foo_test_go_cubre_a_quien_llama(tmp_path, index):
    """A: Use la cubre TestUse; editar Get no tiene llamador sin test."""
    root = tmp_path / "go"
    root.mkdir()
    (root / "foo.go").write_text("package foo\n\nfunc Get() int {\n\treturn 1\n}\n\n"
                                 "func Use() int {\n\treturn Get()\n}\n", encoding="utf-8")
    (root / "foo_test.go").write_text('package foo\n\nimport "testing"\n\n'
                                      "func TestUse(t *testing.T) {\n\tif Use() != 1 {\n"
                                      "\t\tt.Fatal()\n\t}\n}\n", encoding="utf-8")
    index(root)
    assert _edit(root, "foo.go", "\treturn 1") is None


def test_archivo_mas_nuevo_que_el_indice_usa_sus_lineas_reales(tmp_path, index):
    """B: tras añadir 30 líneas arriba, `return 1` sigue siendo f, no lo que había allí."""
    root = tmp_path / "py"
    root.mkdir()
    core = root / "core.py"
    core.write_text("def f():\n    return 1\n\n\ndef g():\n    return f()\n", encoding="utf-8")
    index(root)
    core.write_text("X = 1\n" * 30 + "def f():\n    return 1\n\n\ndef g():\n    return f()\n",
                    encoding="utf-8")
    future = time.time() + 5
    os.utime(core, (future, future))
    assert _edit(root, "core.py", "X = 1\nX = 1") is None, "constantes: no hay símbolo"
    out = _edit(root, "core.py", "    return 1")
    assert out is not None and "`f` (core.py:31)" in out["hookSpecificOutput"]["additionalContext"]


def test_techo_por_defecto_2_mb():
    """C: medido ~6,5k símbolos/MB; a 2 MB (~13k) el hook cuesta ~1 s."""
    if "LEO_GUARD_MAX_INDEX_MB" not in os.environ:
        assert guard_hook._MAX_INDEX_MB == 2.0


def test_total_cortado_por_el_limite_se_dice_con_mas(tmp_path, index):
    """Revisión 17/11: 30 de 66 avisos de leo-code decían «(200 dependents)» cuando el
    recorrido se paraba en 200: la cifra era un tope, no un total."""
    root = tmp_path / "big"
    root.mkdir()
    body = "def f():\n    return 1\n" + "".join(f"\n\ndef g{i}():\n    return f()\n" for i in range(205))
    (root / "core.py").write_text(body, encoding="utf-8")
    index(root)
    out = _edit(root, "core.py", "    return 1")
    assert out is not None and "(200+ dependents)" in out["systemMessage"]
    assert "200+ dependent(s) in total" in out["hookSpecificOutput"]["additionalContext"]


def test_calla_si_el_plazo_vence_durante_el_informe(tmp_path, index, monkeypatch):
    """C: el plazo se mira también entre las fases caras del informe."""
    root = tmp_path / "py"
    root.mkdir()
    (root / "core.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return f()\n",
                                  encoding="utf-8")
    index(root)
    from leo_code.core import boundary
    real = boundary.link_http_edges
    monkeypatch.setattr(boundary, "link_http_edges", lambda caps: (time.sleep(0.3), real(caps))[1])
    monkeypatch.setattr(guard_hook, "_DEADLINE_S", 0.2)
    assert _edit(root, "core.py", "    return 1") is None
