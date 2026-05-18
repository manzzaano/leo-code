#!/usr/bin/env python3
"""
leo/code sidecar auto-start script.
Spawned by leo-code CLI on startup.
Ensures leo-code-mcp is running before the agent starts.
"""
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx

# Monorepo root: packages/leo-code/src/context/sidecar.py → leo-code/
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent


def is_sidecar_running(port: int = 9898) -> bool:
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start_sidecar():
    """Start the sidecar from the monorepo sidecar/ directory."""
    sidecar_dir = _REPO_ROOT / "sidecar"
    kc_rag_dir = _REPO_ROOT / "kc-rag"
    kc_core_dir = _REPO_ROOT / "kc-core"

    # Build PYTHONPATH so subprocess finds leo_mcp, kc_code, kc_core
    paths = [str(sidecar_dir), str(kc_rag_dir), str(kc_core_dir)]
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = os.pathsep.join(paths + ([existing] if existing else []))

    env = {**os.environ, "PYTHONPATH": pythonpath}

    # Try monorepo sidecar first, then global install as fallback
    commands = [
        [sys.executable, "-m", "leo_mcp.server"],
        ["leo-code-mcp"],
    ]

    for cmd in commands:
        try:
            subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            time.sleep(2)
            if is_sidecar_running():
                return True
        except FileNotFoundError:
            continue

    return False


if __name__ == "__main__":
    if is_sidecar_running():
        print("[leo/code] Sidecar KC-RAG already running on :9898")
        sys.exit(0)

    print("[leo/code] Starting sidecar KC-RAG...")
    if start_sidecar():
        print("[leo/code] Sidecar started successfully")
    else:
        print("[leo/code] WARNING: Could not start sidecar.")
        print("[leo/code] Continuing without KC-RAG context...")
