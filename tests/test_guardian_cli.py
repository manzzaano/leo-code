"""Smoke test del CLI standalone `python -m leo_code.core.guardian` (agregado
para que guardian.yml no dependa del CLI del agente, ver PLAN.md) — via
subprocess, igual que tests/test_filectx.py."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def test_no_args_runs_self_check_demo():
    result = subprocess.run(
        [sys.executable, "-m", "leo_code.core.guardian"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT, env=_ENV,
    )
    assert result.returncode == 0, result.stderr
    assert "self-check OK" in result.stdout


def test_symbol_mode_previews_impact(tmp_path):
    (tmp_path / "a.py").write_text(
        "def helper():\n    return 1\n\n\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "leo_code.core.guardian", "-s", "helper", "--repo", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT, env=_ENV,
    )
    assert result.returncode == 0, result.stderr
    assert "helper" in result.stdout
    assert "caller" in result.stdout
