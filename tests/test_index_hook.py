"""index_hook — al abrir sesión en un repo git, indexa en segundo plano.

Se prueba también como PROCESO, que es como lo lanza Claude Code: en SessionStart lo
que el hook escribe en stdout entra en el contexto del agente, así que debe callar.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from leo_code import index_hook

ROOT = Path(__file__).resolve().parents[1]


def _espera(cond, segundos: float) -> bool:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.2)
    return False


def _proceso(stdin: str, env_extra: dict | None = None):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "leo_code.index_hook"], input=stdin,
                          capture_output=True, text=True, env=env, timeout=60)


def test_en_repo_git_lanza_el_indexado(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    lanzados = []
    monkeypatch.setattr(index_hook, "_spawn", lambda cmd: lanzados.append(cmd))
    cmd = index_hook.run({"cwd": str(tmp_path)})
    assert lanzados == [cmd] == [[sys.executable, "-m", "leo_code.cli", "index", str(tmp_path)]]


def test_fuera_de_git_no_lanza_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(index_hook, "_spawn", lambda cmd: pytest.fail("no debía lanzar"))
    assert index_hook.run({"cwd": str(tmp_path)}) is None


def test_la_escotilla_lo_apaga(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("LEO_INDEX_HOOK", "0")
    monkeypatch.setattr(index_hook, "_spawn", lambda cmd: pytest.fail("apagado"))
    assert index_hook.run({"cwd": str(tmp_path)}) is None


@pytest.mark.parametrize("stdin", ["", "basura", "{}", '{"cwd": null}', '{"cwd": "/no/existe"}', "[1, 2]"])
def test_como_proceso_nunca_falla_ni_escribe(stdin):
    p = _proceso(stdin)
    assert p.returncode == 0 and p.stdout == ""


def test_como_proceso_el_indice_aparece_sin_esperarlo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    cache = tmp_path / "cache"
    t0 = time.monotonic()
    p = _proceso(json.dumps({"cwd": str(repo)}), {"LEO_CACHE_DIR": str(cache)})
    assert p.returncode == 0 and p.stdout == ""
    assert time.monotonic() - t0 < 5, "no espera al indexado"
    # lo escribe el hijo desacoplado
    assert _espera(lambda: any(cache.glob("repos/*/index-v*.json.gz")), 60), \
        f"sin índice en {cache}: {list(cache.rglob('*')) if cache.exists() else 'no existe'}"
