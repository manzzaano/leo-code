"""Pytest configuration and fixtures."""

import os
import pytest
from pathlib import Path


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
