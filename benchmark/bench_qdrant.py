"""Setup del Qdrant efimero por subproceso de benchmark, compartido por
leo_runner.py / leo_rag_runner.py / leo_smart_runner.py.

Storage propio y aislado por DIRECTORIO (no por sufijo de PID en la coleccion,
ver engine.py use_process_id=False) — sin esto, corridas paralelas del
benchmark (--batch N) se pisan y degradan a indice en memoria.

Si run_real.py precalento un indice (LEO_QDRANT_PREWARM_PATH), lo copiamos al
directorio aislado del subproceso en vez de arrancar vacio: mismo aislamiento,
sin pagar el parseo+embedding de ~1400 capsulas en cada uno de los 15 tasks x N
subprocesos del batch.
"""

import os
import shutil
import tempfile


def setup_qdrant_path() -> str:
    qdrant_dir = tempfile.mkdtemp(prefix="leo_qdrant_bench_")
    prewarm = os.environ.get("LEO_QDRANT_PREWARM_PATH")
    if prewarm and os.path.isdir(prewarm):
        shutil.rmtree(qdrant_dir, ignore_errors=True)
        shutil.copytree(prewarm, qdrant_dir)
    os.environ["LEO_QDRANT_PATH"] = qdrant_dir
    return qdrant_dir
