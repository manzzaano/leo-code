"""Oráculo de COBERTURA — verifica el guardián contra coverage.py ejecutado de verdad.

Corre la suite bajo coverage.py (ejecución real) y obtiene qué funciones EJECUTAN los
tests. Compara con el alcance estático de leo (`Guardian.is_covered`, cierre de llamadas
desde los tests):

  SOUNDNESS (lo crítico para el guardián): todo símbolo que los tests EJECUTAN debe estar
  en el alcance de leo. Si no → leo daría un falso "SIN test (riesgo)". Cero violaciones.

(La dirección inversa —leo alcanza algo que no se ejecutó— es conservadora y aceptable:
el grafo estático sobre-aproxima; el guardián prefiere avisar de más, no de menos.)

Uso:  python benchmark/coverage_oracle.py
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
ROOT = Path(__file__).parent.parent


def _run_coverage() -> dict:
    """Ejecuta la suite bajo coverage.py y devuelve {archivo_abs: set(líneas ejecutadas)}."""
    subprocess.run([sys.executable, "-m", "coverage", "run", "--source", "leo_code",
                    "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
                   cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    subprocess.run([sys.executable, "-m", "coverage", "json", "-o", "cov.json", "-q"],
                   cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    data = json.loads((ROOT / "cov.json").read_text(encoding="utf-8"))
    (ROOT / "cov.json").unlink(missing_ok=True)
    out = {}
    for f, info in data.get("files", {}).items():
        out[str((ROOT / f).resolve())] = set(info.get("executed_lines", []))
    return out


def run():
    executed = _run_coverage()
    from leo_code.rag.indexer import Indexer
    from leo_code.core.guardian import Guardian
    idx = Indexer(); idx.build(str(ROOT), verbose=False)
    caps = idx.get_capsules()
    g = Guardian(caps)            # Guardian aumenta su propio grafo (dispatch indirecto)

    code_types = {"function", "async_function", "method"}
    dyn_covered = 0
    violations = []   # ejecutado por tests pero leo dice fuera de alcance (falso "SIN test")
    for c in caps.values():
        if c.type not in code_types or not (c.file_path or "").endswith(".py"):
            continue
        sig = (c.signature or "").lstrip()
        if sig.startswith(("from ", "import ")) or "." in c.name:
            continue   # pseudo-cápsulas de import, no son defs reales
        if "/tests/" in (c.file_path or "").replace("\\", "/") or c.name.startswith("test_"):
            continue   # los propios tests no cuentan
        # Dispatch IMPLÍCITO (fuera del alcance de un grafo por nombre): dunders se invocan
        # vía f-string/operadores (__str__, __del__…) y @property vía acceso de atributo.
        nm = c.name
        if nm.startswith("__") and nm.endswith("__"):
            continue
        if "property" in (c.properties or {}).get("decorators", ""):
            continue
        lines = executed.get(str(Path(c.file_path).resolve()), set())
        # CUERPO ejecutado, no la línea `def` (que corre al importar al definir la función).
        ran = any(c.start_line < ln <= c.end_line for ln in lines)
        if ran:
            dyn_covered += 1
            if not g.is_covered(c.name):
                violations.append((c.name, c.file_path))

    ok = len(violations) == 0
    print(f"funciones EJECUTADAS por los tests (coverage.py): {dyn_covered}")
    print(f"de esas, leo las alcanza estáticamente: {dyn_covered - len(violations)}")
    print(f"SOUNDNESS cobertura: {'✅ 0 falsos SIN-test' if ok else f'❌ {len(violations)} falsos'}")
    for n, f in violations[:15]:
        print(f"    falso SIN-test: {n}  ({f})")
    return ok, dyn_covered, len(violations)


if __name__ == "__main__":
    ok, n, viol = run()
    sys.exit(0 if ok else 1)
