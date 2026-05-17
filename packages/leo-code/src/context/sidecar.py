#!/usr/bin/env python3
"""
leo/code sidecar auto-start script.
Spawned by leo-code CLI on startup.
Ensures leo-code-mcp is running before the agent starts.
"""
import subprocess
import sys
import time
import httpx


def is_sidecar_running(port: int = 9898) -> bool:
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start_sidecar():
    """Try to start leo-code-mcp via pip package or local install."""
    commands = [
        [sys.executable, "-m", "leo_mcp.server"],
        ["leo-code-mcp"],
    ]

    for cmd in commands:
        try:
            proc = subprocess.Popen(
                cmd,
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
        print("[leo/code] WARNING: Could not start sidecar. Install: pip install leo-code-mcp")
        print("[leo/code] Continuing without KC-RAG context...")
