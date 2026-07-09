"""Pytest configuration and fixtures."""

import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path, monkeypatch):
    """record_query() escribe a ~/.leo-code/usage.jsonl (global, real) — sin esto,
    cualquier test que ejercite record_query (directo o via AgentLoop) ensucia el
    log real del usuario con entradas de test."""
    import leo_code.core.metrics as metrics
    monkeypatch.setattr(metrics, "USAGE_LOG_PATH", tmp_path / "usage.jsonl")


@pytest.fixture
def mini_repo_path():
    """Path to mini repo fixture directory."""
    return str(Path(__file__).parent / "fixtures" / "mini_repo")


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Temporary cache directory for tests."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    original_cache = os.environ.get("LEO_CACHE_DIR")
    os.environ["LEO_CACHE_DIR"] = str(cache_dir)
    yield str(cache_dir)
    if original_cache:
        os.environ["LEO_CACHE_DIR"] = original_cache
    else:
        os.environ.pop("LEO_CACHE_DIR", None)
