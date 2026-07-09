"""leo-code-mcp: KC-RAG sidecar server for Leo-Code.

Endpoints:
  GET  /health              — health check
  POST /context             — KC-RAG: indexer → Qdrant + BM25 → compress → contexto
  POST /search              — Búsqueda semántica en el KG
  POST /index               — Indexar un repositorio
  POST /preindex            — Pre-indexar sin consultar (background)
  GET  /stats               — Estadísticas del índice
  GET  /metrics             — Métricas de uso (tokens ahorrados, latencia, etc.)
  GET  /metrics/prometheus  — Métricas en formato Prometheus (text exposition)
  GET  /benchmark           — Métricas históricas del benchmark
  GET  /sessions            — Listar sesiones guardadas

Ejecutar: python -m leo_code.server.server  (puerto 9898)
         leo-code-mcp --workers 4  (si instalado vía pip)
"""

import argparse
import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn

from leo_code.core.metrics import get_metrics, MetricsSnapshot
from leo_code.logging_config import setup_logging

# El MOTOR vive en leo_code/engine.py (sin FastAPI). server.py es solo el wrapper
# HTTP: importa el motor en vez de duplicarlo (fuente única de verdad).
from leo_code import engine
from leo_code.engine import (
    compute_context, _ensure_indexed, _do_index, _index_executor,
    _get_indexer, _get_vector_store, _get_bm25,
    _cache_context_result, _invalidate_cache, _load_index_from_disk,
)


class ContextRequest(BaseModel):
    query: str
    repo_path: str = "."
    task_type: str = "code_query"
    budget_tokens: int = 2000


class SearchRequest(BaseModel):
    query: str
    repo_path: str = "."
    top_k: int = 10


class IndexRequest(BaseModel):
    repo_path: str
    languages: str = "python,text"


class ContextResponse(BaseModel):
    context: str
    tokens: int
    task_type: str
    capsules_total: int


class SearchResponse(BaseModel):
    results: list[dict]
    total_capsules: int


class StatsResponse(BaseModel):
    total_capsules: int
    total_files: int
    by_type: dict
    repos_indexed: list[str]


class BenchmarkResponse(BaseModel):
    queries_total: int
    tokens_saved_vs_baseline: int
    tokens_used: int
    task_type_distribution: dict
    top_5_tasks: list[dict]


_rate_limits: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 10
_RATE_LIMIT_MAX = 30


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    _rate_limits.setdefault(ip, [])
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[leo-mcp] Arrancando servidor KC-RAG en puerto 9898...")
    _load_index_from_disk()
    try:
        from leo_code.core.cache import init as cache_init, is_available
        cache_init()
        if is_available():
            print("[leo-mcp] Redis cache conectado")
    except Exception:
        pass
    yield
    print("[leo-mcp] Apagando.")


app = FastAPI(title="Leo-Code MCP", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "leo-code-mcp", "version": "0.2.0"}


@app.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest, request: Request):
    """KC-RAG: indexer → Qdrant + BM25 → compress → contexto comprimido."""
    t_start = time.time()
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")
    try:
        repo = os.path.abspath(req.repo_path)
        await _ensure_indexed(repo)

        cache_key = f"{req.query}|{repo}|{req.task_type}|{req.budget_tokens}"
        try:
            from leo_code.core.cache import get_cached_result
            cached = get_cached_result(cache_key)
            if cached:
                get_metrics().record_cache_hit()
                get_metrics().record_query(0, int((time.time() - t_start) * 1000), repo_path=repo)
                return ContextResponse(**cached)
        except Exception:
            pass
        get_metrics().record_cache_miss()

        result = compute_context(repo, req.query, req.task_type, req.budget_tokens)
        _cache_context_result(cache_key, result)
        get_metrics().record_query(result["tokens"], int((time.time() - t_start) * 1000), repo_path=repo)
        return ContextResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """Búsqueda semántica en el KG de código."""
    try:
        repo = os.path.abspath(req.repo_path)
        await _ensure_indexed(repo)

        idx = _get_indexer()
        all_caps = idx.get_capsules()
        repo_prefix = repo + os.sep
        caps = {
            k: v for k, v in all_caps.items()
            if os.path.abspath(v.file_path).startswith(repo_prefix) or
               os.path.abspath(v.file_path) == repo
        }
        vs = _get_vector_store(repo)

        top_ids = vs.search(req.query, top_k=req.top_k)

        results = []
        for rid in top_ids:
            if rid in caps:
                c = caps[rid]
                results.append({
                    "id": c.id, "name": c.name, "type": c.type,
                    "file_path": c.file_path, "signature": c.signature,
                    "docstring": c.docstring or "",
                })

        return SearchResponse(results=results, total_capsules=len(caps))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index")
async def index_repo(req: IndexRequest):
    """Indexa un repositorio."""
    try:
        repo = os.path.abspath(req.repo_path)
        langs = [l.strip() for l in req.languages.split(",")]
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(_index_executor, _do_index, repo, langs, True)
        _invalidate_cache()
        get_metrics().record_index(count)
        return {"status": "ok", "capsules": count, "repo": repo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/preindex")
async def preindex(req: IndexRequest):
    """Pre-indexa en background sin esperar."""
    repo = os.path.abspath(req.repo_path)
    langs = [l.strip() for l in req.languages.split(",")]
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_index_executor, _do_index, repo, langs, True)
    return {"status": "indexing", "repo": repo}


@app.get("/stats", response_model=StatsResponse)
async def stats(repo_path: Optional[str] = None):
    """Estadísticas del índice. Si repo_path se especifica, filtra por repo."""
    idx = _get_indexer()
    if repo_path:
        repo = os.path.abspath(repo_path)
        repo_prefix = repo + os.sep
        all_caps = idx.get_capsules()
        caps = {
            k: v for k, v in all_caps.items()
            if os.path.abspath(v.file_path).startswith(repo_prefix) or
               os.path.abspath(v.file_path) == repo
        }
        by_type: dict[str, int] = {}
        files: set[str] = set()
        for c in caps.values():
            by_type[c.type] = by_type.get(c.type, 0) + 1
            files.add(c.file_path)
        return StatsResponse(
            total_capsules=len(caps),
            total_files=len(files),
            by_type=by_type,
            repos_indexed=list(engine._indexed_repos),
        )
    s = idx.stats()
    return StatsResponse(
        total_capsules=s["total_capsules"],
        total_files=s["total_files"],
        by_type=s["by_type"],
        repos_indexed=list(engine._indexed_repos),
    )


@app.get("/metrics")
async def metrics():
    """Métricas de uso: tokens ahorrados, latencia, cache hits."""
    snap = get_metrics().snapshot()
    return {
        "queries_total": snap.queries_total,
        "tokens_saved_vs_baseline": snap.tokens_saved,
        "tokens_used": snap.tokens_used,
        "cache_hit_rate": round(snap.cache_hits / max(snap.cache_hits + snap.cache_misses, 1), 3),
        "avg_latency_ms": round(snap.avg_latency_ms, 1),
        "p50_latency_ms": snap.p50_latency_ms,
        "p99_latency_ms": snap.p99_latency_ms,
        "capsules_indexed": snap.capsules_indexed,
        "repos_indexed": snap.repos_indexed,
        "uptime_seconds": int(snap.uptime_seconds),
    }


@app.get("/metrics/prometheus")
async def metrics_prometheus():
    """Métricas en formato Prometheus text exposition (scrapeable por Prometheus/Grafana)."""
    snap = get_metrics().snapshot()
    return PlainTextResponse(snap.to_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/benchmark", response_model=BenchmarkResponse)
async def benchmark():
    """Métricas históricas del benchmark: queries, tokens, task_types, top tareas."""
    snap = get_metrics().snapshot()
    tasks_map: dict[str, str] = {}
    summary_path = Path("benchmark/results_real/summary.json")
    tasks_json_path = Path("benchmark/tasks.json")
    results_tasks: list[dict] = []
    dist: dict[str, int] = {}

    try:
        if tasks_json_path.exists():
            tasks_raw = json.loads(tasks_json_path.read_text(encoding="utf-8"))
            tasks_map = {t["id"]: t["type"] for t in tasks_raw}

        if summary_path.exists():
            entries = json.loads(summary_path.read_text(encoding="utf-8"))
            entries = entries if isinstance(entries, list) else [entries]
            for item in entries:
                tid = item.get("task_id", "")
                ttype = tasks_map.get(tid, "unknown")
                dist[ttype] = dist.get(ttype, 0) + 1
                results_tasks.append({
                    "task_id": tid,
                    "type": ttype,
                    "model": item.get("system", ""),
                    "mode": item.get("mode", ""),
                    "score": item.get("score_total", 0),
                    "tokens": item.get("tokens", 0),
                    "duration_s": round(item.get("duration_ms", 0) / 1000, 1),
                })
    except Exception:
        pass

    results_tasks.sort(key=lambda x: x.get("score", 0), reverse=True)

    return BenchmarkResponse(
        queries_total=snap.queries_total,
        tokens_saved_vs_baseline=snap.tokens_saved,
        tokens_used=snap.tokens_used,
        task_type_distribution=dist,
        top_5_tasks=results_tasks[:5],
    )


@app.get("/sessions")
async def list_sessions(limit: int = Query(20, ge=1, le=100)):
    """Lista sesiones guardadas (multi-turn)."""
    try:
        from leo_code.session import SessionManager
        sm = SessionManager()
        sessions = sm.list_sessions(limit)
        return {
            "sessions": [
                {
                    "id": s.id,
                    "repo_path": s.repo_path,
                    "model": s.model,
                    "message_count": s.message_count,
                    "total_tokens": s.total_tokens,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in sessions
            ],
            "total": len(sessions),
        }
    except Exception as e:
        return {"error": str(e), "sessions": []}


_global_plugin_manager = None


@app.get("/plugins")
async def list_plugins():
    """Lista plugins cargados y su estado."""
    if _global_plugin_manager is None:
        return {"plugins": [], "total": 0}
    info = _global_plugin_manager.info()
    return {
        "plugins": [{"name": p.name, "type": p.type, "running": p.running,
                      "tool_count": getattr(p, 'tool_count', 0), "version": p.version}
                     for p in info],
        "total": len(info),
    }


@app.get("/skills")
async def list_skills():
    """Lista skills disponibles y sus triggers."""
    from leo_code.skills import SkillManager
    sm = SkillManager()
    sm.load_skills(".")
    return {
        "skills": [{"name": s.name, "description": s.description, "source": s.source,
                    "task_types": s.task_types, "triggers": s.triggers[:5], "priority": s.priority}
                   for s in sm.list_all()],
        "total": len(sm.list_all()),
    }


def main():
    global _global_plugin_manager
    parser = argparse.ArgumentParser(description="Leo-Code MCP Server")
    parser.add_argument("--workers", type=int, default=1, help="Número de workers uvicorn (default 1)")
    parser.add_argument("--port", type=int, default=9898, help="Puerto (default 9898)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")
    parser.add_argument("--plugins", default="", help="Path a leo-code.json con configuración de plugins")
    args = parser.parse_args()
    setup_logging()

    if args.plugins:
        from leo_code.plugins import PluginManager
        _global_plugin_manager = PluginManager(config_path=args.plugins, repo_path=".")
        _global_plugin_manager.init()

    print(f"[leo-mcp] Leo-Code MCP Server v0.2.0 (workers={args.workers})")
    print("[leo-mcp] Endpoints:")
    print(f"  GET  http://{args.host}:{args.port}/health")
    print(f"  POST http://{args.host}:{args.port}/context")
    print(f"  POST http://{args.host}:{args.port}/search")
    print(f"  POST http://{args.host}:{args.port}/index")
    print(f"  POST http://{args.host}:{args.port}/preindex")
    print(f"  GET  http://{args.host}:{args.port}/stats")
    print(f"  GET  http://{args.host}:{args.port}/metrics")
    print(f"  GET  http://{args.host}:{args.port}/benchmark")
    print(f"  GET  http://{args.host}:{args.port}/sessions")
    print(f"  GET  http://{args.host}:{args.port}/plugins")
    if _global_plugin_manager:
        plugins = _global_plugin_manager.info()
        if plugins:
            print(f"[leo-mcp] Plugins: {len(plugins)} cargados ({', '.join(p.name for p in plugins)})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=args.workers)


if __name__ == "__main__":
    main()
