"""Staleness de cache de indice: compartido entre engine.py (servidor/MCP) y
AgentLoop (agente nativo) para que ambos caminos usen el mismo criterio de
cuando un cache en disco necesita sync incremental."""

import os
import time
from pathlib import Path


def cache_ttl_seconds() -> int:
    """Leido en el momento de uso (no constante congelada al importar) para que
    LEO_CACHE_TTL sea testeable con monkeypatch.setenv sin importlib.reload."""
    return int(os.environ.get("LEO_CACHE_TTL", "3600"))  # 1h: dev tool local, no urgente


def is_cache_stale(cache_path: Path, repo_path: str) -> bool:
    """Checks if cache is older than the newest file in repo, OR older than
    LEO_CACHE_TTL seconds. Una eliminacion/renombrado sin ningun otro archivo
    tocado nunca bumpea un mtime — el TTL fuerza un sync periodico que lo detecta
    (Indexer.sync() SI calcula deleted correctamente, solo faltaba dispararlo)."""
    try:
        cache_time = cache_path.stat().st_mtime
        if time.time() - cache_time > cache_ttl_seconds():
            return True
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules", ".venv", "venv"}]
            for file in files:
                if file.endswith((".py", ".js", ".ts", ".rs", ".go")):
                    file_path = os.path.join(root, file)
                    if os.path.getmtime(file_path) > cache_time:
                        return True
        return False
    except Exception:
        return True
