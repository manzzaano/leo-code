"""Redis cache con circuit breaker real.

Circuit breaker: 3 fallos consecutivos → circuito abierto 30s → half-open → recupera.
Redis URL configurable via LEO_REDIS_URL.
"""

import json
import hashlib
import os
import time
import threading
from typing import Optional

_redis = None
_client = None

# Circuit breaker state
_failures = 0
_last_failure = 0.0
CB_THRESHOLD = 3
CB_TIMEOUT = 30  # seconds open before half-open


def _is_circuit_open() -> bool:
    global _failures, _last_failure
    if _failures >= CB_THRESHOLD:
        if time.time() - _last_failure > CB_TIMEOUT:
            _failures = 0
            return False
        return True
    return False


def _record_failure():
    global _failures, _last_failure
    _failures += 1
    _last_failure = time.time()
    if _client:
        try:
            _client.close()
        except Exception:
            pass


def _record_success():
    global _failures
    _failures = 0


def _safe_op(fn, *args, **kwargs):
    if not _client or _is_circuit_open():
        return None
    try:
        result = fn(*args, **kwargs)
        _record_success()
        return result
    except Exception:
        _record_failure()
        return None


def init(redis_url: str = ""):
    global _redis, _client
    if not redis_url:
        redis_url = os.getenv("LEO_REDIS_URL", "redis://localhost:6379")
    try:
        import redis as _redis_mod
        _redis = _redis_mod
        _client = _redis_mod.from_url(redis_url, socket_connect_timeout=0.2, decode_responses=True)
        _client.ping()
        _record_success()
    except Exception:
        _client = None


def is_available() -> bool:
    return _client is not None and not _is_circuit_open()


def _query_key(query: str) -> str:
    return "query:" + hashlib.md5(query.lower().strip().encode()).hexdigest()


def _subgraph_key(entity_id: str) -> str:
    return f"subgraph:{entity_id}"


def get_cached_result(query: str) -> Optional[dict]:
    raw = _safe_op(_client.get, _query_key(query)) if _client else None
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def cache_result(query: str, result: dict, ttl: int = 60):
    _safe_op(_client.setex, _query_key(query), ttl, json.dumps(result, ensure_ascii=False))


def cache_subgraph(entity_id: str, subgraph: dict, ttl: int = 300):
    _safe_op(_client.setex, _subgraph_key(entity_id), ttl, json.dumps(subgraph, ensure_ascii=False))


def get_cached_subgraph(entity_id: str) -> Optional[dict]:
    raw = _safe_op(_client.get, _subgraph_key(entity_id)) if _client else None
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def cache_ontology(domain: str, ontology: dict):
    _safe_op(_client.set, f"ontology:{domain}", json.dumps(ontology, ensure_ascii=False))


def get_cached_ontology(domain: str) -> Optional[dict]:
    raw = _safe_op(_client.get, f"ontology:{domain}") if _client else None
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def clear_cache(pattern: str = "*"):
    def _clear():
        keys = _client.keys(pattern)
        if keys:
            _client.delete(*keys)
    _safe_op(_clear)
