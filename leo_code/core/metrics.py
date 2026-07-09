"""Metrics — observabilidad para leo-code.

Trackea: queries totales, tokens ahorrados vs baseline, latencia, cache hits.
Endpoint /metrics en el sidecar.
"""

import json
import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Log global append-only, analogo a los .jsonl de sesion de Claude Code
# (~/.claude/projects/**/*.jsonl) pero para leo-code: una linea por query
# completada, across TODOS los repos/procesos. Alimenta leo_code/meter/.
USAGE_LOG_PATH = Path.home() / ".leo-code" / "usage.jsonl"


def _append_usage_log(entry: dict) -> None:
    """Best-effort: nunca debe romper una query real por un fallo de disco/permisos."""
    try:
        USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# Baseline = tokens que un agente sin leo (Claude Code/opencode) consumiría leyendo
# los archivos del subgrafo para responder. benchmark/token_efficiency.py midió que
# el baseline realista multi-archivo promedia ~27k tok/query en este repo, así que
# 20000 es una estimación CONSERVADORA (subestima el ahorro), no un número inventado.
BASELINE_TOKENS_PER_QUERY = int(os.environ.get("LEO_BASELINE_TOKENS", "20000"))


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
    t_index_ms: float = 0
    t_classify_ms: float = 0
    t_search_ms: float = 0
    t_compress_ms: float = 0
    t_llm_ms: float = 0

    def to_prometheus(self) -> str:
        """Prometheus text exposition format — sin dependencia prometheus_client,
        16 campos numéricos simples no la justifican."""
        fields = [
            ("queries_total", "counter", self.queries_total),
            ("tokens_saved", "counter", self.tokens_saved),
            ("tokens_used", "counter", self.tokens_used),
            ("cache_hits", "counter", self.cache_hits),
            ("cache_misses", "counter", self.cache_misses),
            ("avg_latency_ms", "gauge", self.avg_latency_ms),
            ("p50_latency_ms", "gauge", self.p50_latency_ms),
            ("p99_latency_ms", "gauge", self.p99_latency_ms),
            ("capsules_indexed", "gauge", self.capsules_indexed),
            ("repos_indexed", "gauge", self.repos_indexed),
            ("uptime_seconds", "counter", self.uptime_seconds),
            ("t_index_ms", "gauge", self.t_index_ms),
            ("t_classify_ms", "gauge", self.t_classify_ms),
            ("t_search_ms", "gauge", self.t_search_ms),
            ("t_compress_ms", "gauge", self.t_compress_ms),
            ("t_llm_ms", "gauge", self.t_llm_ms),
        ]
        lines = []
        for name, mtype, value in fields:
            metric = f"leo_code_{name}"
            lines.append(f"# HELP {metric} {name.replace('_', ' ')}")
            lines.append(f"# TYPE {metric} {mtype}")
            lines.append(f"{metric} {value}")
        return "\n".join(lines) + "\n"


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
        self._phase_timings = {
            "t_index_ms": [],
            "t_classify_ms": [],
            "t_search_ms": [],
            "t_compress_ms": [],
            "t_llm_ms": [],
        }

    def record_query(self, tokens: int, latency_ms: int,
                     t_index_ms: float = 0, t_classify_ms: float = 0,
                     t_search_ms: float = 0, t_compress_ms: float = 0,
                     t_llm_ms: float = 0, repo_path: str = "", model: str = ""):
        with self._lock:
            self._queries += 1
            self._tokens_used += tokens
            self._latencies.append(latency_ms)
            if len(self._latencies) > 10_000:
                self._latencies = self._latencies[-5_000:]
            self._phase_timings["t_index_ms"].append(t_index_ms)
            self._phase_timings["t_classify_ms"].append(t_classify_ms)
            self._phase_timings["t_search_ms"].append(t_search_ms)
            self._phase_timings["t_compress_ms"].append(t_compress_ms)
            self._phase_timings["t_llm_ms"].append(t_llm_ms)
        _append_usage_log({
            "ts": datetime.now(timezone.utc).isoformat(),
            "repo_path": repo_path,
            "model": model,
            "tokens": tokens,
            "latency_ms": latency_ms,
        })

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

            def _avg(lst: list[float]) -> float:
                return sum(lst) / len(lst) if lst else 0

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
                t_index_ms=_avg(self._phase_timings["t_index_ms"]),
                t_classify_ms=_avg(self._phase_timings["t_classify_ms"]),
                t_search_ms=_avg(self._phase_timings["t_search_ms"]),
                t_compress_ms=_avg(self._phase_timings["t_compress_ms"]),
                t_llm_ms=_avg(self._phase_timings["t_llm_ms"]),
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
