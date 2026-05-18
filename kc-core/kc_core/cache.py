"""Redis cache estratificado L1/L2/L3 con circuit breaker.

L1: ontología (permanente)
L2: subgrafos (TTL configurable, default 300s)
L3: resultados de query (TTL configurable, default 60s)
"""

import json
import hashlib
from typing import Optional

_redis = None
_client = None


def init(redis_url: str = "redis://localhost:6379", socket_timeout: float = 0.1):
    """Inicializa la conexión Redis."""
    global _redis, _client
    try:
        import redis as _redis_mod
        _redis = _redis_mod
        _client = _redis_mod.from_url(redis_url, socket_connect_timeout=socket_timeout, decode_responses=True)
        _client.ping()
    except Exception:
        _client = None


def is_available() -> bool:
    return _client is not None


def _query_key(query: str) -> str:
    return "query:" + hashlib.md5(query.lower().strip().encode()).hexdigest()


def _subgraph_key(entity_id: str) -> str:
    return f"subgraph:{entity_id}"


def get_cached_result(query: str) -> Optional[dict]:
    if not _client:
        return None
    try:
        raw = _client.get(_query_key(query))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def cache_result(query: str, result: dict, ttl: int = 60):
    if not _client:
        return
    try:
        _client.setex(_query_key(query), ttl, json.dumps(result, ensure_ascii=False))
    except Exception:
        pass


def cache_subgraph(entity_id: str, subgraph: dict, ttl: int = 300):
    if not _client:
        return
    try:
        _client.setex(_subgraph_key(entity_id), ttl, json.dumps(subgraph, ensure_ascii=False))
    except Exception:
        pass


def get_cached_subgraph(entity_id: str) -> Optional[dict]:
    if not _client:
        return None
    try:
        raw = _client.get(_subgraph_key(entity_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def cache_ontology(domain: str, ontology: dict):
    if not _client:
        return
    try:
        _client.set(f"ontology:{domain}", json.dumps(ontology, ensure_ascii=False))
    except Exception:
        pass


def get_cached_ontology(domain: str) -> Optional[dict]:
    if not _client:
        return None
    try:
        raw = _client.get(f"ontology:{domain}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def clear_cache(pattern: str = "*"):
    if not _client:
        return
    try:
        keys = _client.keys(pattern)
        if keys:
            _client.delete(*keys)
    except Exception:
        pass
