"""Chequeo (f) de la auditoría: pico de RAM del camino del producto (arranque en frío y en
caliente + get_context) medido en un proceso hijo limpio, contra un tope fijo."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmark"))
import audit_formal  # noqa: E402


def test_peak_mb_mide_algo_razonable():
    assert 5 < audit_formal._peak_mb() < 10_000


def test_check_f_pasa_en_repo_pequeno_y_mide_frio_y_caliente(mini_repo_path):
    ok, detail = audit_formal.check_f([str(mini_repo_path)])
    assert ok, detail
    assert "frío" in detail and "caliente" in detail and "MB" in detail


def test_check_f_falla_si_el_pico_supera_el_tope(mini_repo_path, monkeypatch):
    monkeypatch.setattr(audit_formal, "_MEM_LIMIT_MB", 1)
    ok, detail = audit_formal.check_f([str(mini_repo_path)])
    assert not ok, detail


def test_el_hijo_no_hereda_el_pico_del_padre():
    """En Linux `ru_maxrss` sobrevive a exec: el hijo reportaba el pico de la auditoría
    entera (776 MB en CI, igual en frío y en caliente)."""
    import subprocess
    lastre = bytearray(400 * 2**20)   # noqa: F841 — sube el pico del padre
    lastre[::4096] = b"x" * len(lastre[::4096])
    code = (f"import sys; sys.path.insert(0, {str(Path(audit_formal.__file__).parent)!r}); "
            "import audit_formal; print(audit_formal._peak_mb())")
    hijo = float(subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, check=True).stdout)
    assert hijo < 200, hijo
