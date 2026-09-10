"""Smoke test del CLI leo_code.filectx: vista comprimida de un archivo vía subprocess
(es un script standalone con sys.exit, no una función importable)."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_filectx(repo: Path, file: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "leo_code.filectx", file, "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT,
    )


def test_filectx_prints_compressed_view(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    result = _run_filectx(tmp_path, "greet.py")

    assert result.returncode == 0, result.stderr
    assert "COMPRIMIDO" in result.stdout
    assert "say_hello" in result.stdout


def test_filectx_exit_3_when_file_not_indexed(tmp_path):
    (tmp_path / "greet.py").write_text(
        "def say_hello():\n    return 'hi'\n", encoding="utf-8"
    )
    result = _run_filectx(tmp_path, "no_existe.py")

    assert result.returncode == 3
