"""Metrics — observabilidad para leo-code.

Trackea: queries totales, tokens ahorrados vs baseline, latencia, cache hits.
Endpoint /metrics en el sidecar.
"""

import time
import threading
from dataclasses import dataclass, field


BASELINE_TOKENS_PER_QUERY = 20_000  # opencode promedio por query


@dataclass
class MetricsSnapshot:
    queries_total: int = 0
    tokens_saved: int = 0
    tokens_used: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    avg_latency_ms: float = 0
    p50_latency_ms: float = 0
    p99_latency_ms: float = 0
    capsules_indexed: int = 0
    repos_indexed: int = 0
    uptime_seconds: float = 0


class MetricsTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._queries = 0
        self._tokens_used = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._latencies: list[int] = []
        self._capsules = 0
        self._repos = 0

    def record_query(self, tokens: int, latency_ms: int):
        with self._lock:
            self._queries += 1
            self._tokens_used += tokens
            self._latencies.append(latency_ms)
            if len(self._latencies) > 10_000:
                self._latencies = self._latencies[-5_000:]

    def record_cache_hit(self):
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self):
        with self._lock:
            self._cache_misses += 1

    def record_index(self, capsules: int):
        with self._lock:
            self._capsules = max(self._capsules, capsules)
            self._repos += 1

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            baseline = self._queries * BASELINE_TOKENS_PER_QUERY
            saved = max(0, baseline - self._tokens_used)
            latencies = sorted(self._latencies) if self._latencies else [0]

            return MetricsSnapshot(
                queries_total=self._queries,
                tokens_saved=saved,
                tokens_used=self._tokens_used,
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                avg_latency_ms=sum(self._latencies) / max(len(self._latencies), 1),
                p50_latency_ms=latencies[len(latencies) // 2],
                p99_latency_ms=latencies[int(len(latencies) * 0.99)] if len(latencies) > 100 else latencies[-1],
                capsules_indexed=self._capsules,
                repos_indexed=self._repos,
                uptime_seconds=time.time() - self._start_time,
            )

    @property
    def cache_hit_rate(self) -> float:
        total = self._cache_hits + self._cache_misses
        return self._cache_hits / total if total > 0 else 0

    @property
    def total_tokens_saved(self) -> int:
        baseline = self._queries * BASELINE_TOKENS_PER_QUERY
        return max(0, baseline - self._tokens_used)


# Singleton global
_metrics = MetricsTracker()


def get_metrics() -> MetricsTracker:
    return _metrics
