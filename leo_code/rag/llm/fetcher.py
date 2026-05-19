"""ModelFetcher: carga catálogo de modelos desde models.dev con cache en disco.

Patrón:
- Cache en disco (5 min TTL)
- Fetch remoto con timeout
- Graceful degradation (fallback a vacío)
- Background refresh cada 60 min
"""

import json
import time
from pathlib import Path
from typing import Optional

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_DIR = Path.home() / ".kc-code" / "cache"
CACHE_FILE = CACHE_DIR / "models.json"
CACHE_TTL = 300       # 5 min disco
REFRESH_INTERVAL = 3600  # 60 min background


class ModelFetcher:
    """Carga y cachea el catálogo de modelos desde models.dev."""

    def __init__(self, url: str = MODELS_DEV_URL):
        self._url = url
        self._last_fetch = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def load(self, force: bool = False) -> dict:
        """Carga el catálogo: cache → remote → empty."""
        if not force:
            data = self._from_cache()
            if data:
                return data

        data = self._from_remote()
        if data:
            return data

        return {}

    def _from_cache(self) -> Optional[dict]:
        """Lee del cache en disco si está dentro del TTL."""
        try:
            if not CACHE_FILE.exists():
                return None
            mtime = CACHE_FILE.stat().st_mtime
            if time.time() - mtime > CACHE_TTL:
                return None
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _from_remote(self) -> Optional[dict]:
        """Fetch desde models.dev y guarda en cache."""
        try:
            import httpx
            resp = httpx.get(self._url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._last_fetch = time.time()
            return data
        except Exception:
            return None

    def refresh_if_stale(self):
        """Refresca si ha pasado el intervalo de refresh."""
        if time.time() - self._last_fetch > REFRESH_INTERVAL:
            self.load(force=True)

    def get_provider(self, provider_id: str) -> Optional[dict]:
        """Obtiene datos de un provider específico."""
        data = self.load()
        return data.get(provider_id)

    def get_model_ids(self, provider_id: str, active_only: bool = True) -> list[str]:
        """Lista IDs de modelos para un provider."""
        provider = self.get_provider(provider_id)
        if not provider:
            return []
        models = provider.get("models", {})
        if active_only:
            return [mid for mid, m in models.items() if m.get("status") != "deprecated"]
        return list(models.keys())

    def get_model_info(self, provider_id: str, model_id: str) -> Optional[dict]:
        """Obtiene info de un modelo específico."""
        provider = self.get_provider(provider_id)
        if not provider:
            return None
        return provider.get("models", {}).get(model_id)
