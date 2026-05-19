"""leo-code-mcp: KC-RAG sidecar server for Leo-Code.

Endpoints:
  GET  /health              — health check
  POST /context             — KC-RAG: indexer → Qdrant → compress → contexto
  POST /search              — Búsqueda semántica en el KG
  POST /index               — Indexar un repositorio
  POST /preindex            — Pre-indexar sin consultar (background)
  GET  /stats               — Estadísticas del índice

Ejecutar: python -m leo_mcp.server  (puerto 9898)
         leo-code-mcp --workers 4  (si instalado vía pip)
"""

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Monorepo paths: sidecar/leo_mcp/server.py → leo-code/ → kc-rag/ + kc-core/
_ROOT = Path(__file__).parent.parent.parent  # leo-code/
sys.path.insert(0, str(_ROOT / "kc-rag"))
sys.path.insert(0, str(_ROOT / "kc-core"))

_CACHE_DIR = Path("./cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_INDEX_PATH = _CACHE_DIR / "kc_index.json.gz"
_REPOS_PATH = _CACHE_DIR / "kc_indexed_repos.json"
_LOCK_PATH = _CACHE_DIR / "kc_index.lock"

_indexer = None
_vector_stores: dict[str, object] = {}
_indexed_repos: set[str] = set()
_index_lock = threading.Lock()
_index_executor = ThreadPoolExecutor(max_workers=1)


def _acquire_file_lock(timeout: int = 30) -> bool:
    start = time.time()
    while True:
        try:
            _LOCK_PATH.mkdir()
            return True
        except FileExistsError:
            if time.time() - start > timeout:
                return False
            time.sleep(0.1)


def _release_file_lock():
    try:
        _LOCK_PATH.rmdir()
    except (FileNotFoundError, OSError):
        pass


def _load_indexed_repos():
    global _indexed_repos
    if _REPOS_PATH.exists():
        try:
            _indexed_repos = set(json.loads(_REPOS_PATH.read_text(encoding="utf-8")))
        except Exception:
            _indexed_repos = set()


def _save_indexed_repos():
    _REPOS_PATH.write_text(json.dumps(sorted(_indexed_repos)), encoding="utf-8")


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


def _get_indexer():
    global _indexer
    if _indexer is None:
        from kc_code.indexer import Indexer
        _indexer = Indexer()
    return _indexer


def _get_vector_store(repo_path: str):
    if repo_path not in _vector_stores:
        from kc_code.kc_rag.vector_store import VectorStore
        _vector_stores[repo_path] = VectorStore(
            collection_name=f"leo_mcp_{abs(hash(repo_path)) % 10000}",
            path="./cache/qdrant_leo",
        )
    return _vector_stores[repo_path]


def _repo_caps(idx, repo_path: str) -> list:
    """Devuelve solo las capsulas del repo especificado del indexer global."""
    repo_prefix = repo_path + os.sep
    return [
        v for v in idx.get_capsules().values()
        if os.path.abspath(v.file_path).startswith(repo_prefix) or
           os.path.abspath(v.file_path) == repo_path
    ]


async def _ensure_indexed(repo_path: str):
    global _indexed_repos
    repo = os.path.abspath(repo_path)
    with _index_lock:
        if repo in _indexed_repos:
            return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_index_executor, _do_index, repo)


def _do_index(repo: str, languages: list[str] | None = None, verbose: bool = False) -> int:
    """Ejecuta la indexación (bloqueante). Se llama desde run_in_executor o /index."""
    global _indexed_repos
    idx = _get_indexer()
    if _acquire_file_lock():
        try:
            _load_index_from_disk()
            count = idx.build(repo, languages=languages or ["python", "text"], verbose=verbose)
            vs = _get_vector_store(repo)
            vs.add(_repo_caps(idx, repo))
            _indexed_repos.add(repo)
            _save_index_to_disk()
            _save_indexed_repos()
            return count
        finally:
            _release_file_lock()
    # Fallback without lock
    count = idx.build(repo, languages=languages or ["python", "text"], verbose=verbose)
    vs = _get_vector_store(repo)
    vs.add(_repo_caps(idx, repo))
    with _index_lock:
        _indexed_repos.add(repo)
    return count


def _load_index_from_disk():
    global _indexed_repos
    if _INDEX_PATH.exists():
        idx = _get_indexer()
        idx.load(str(_INDEX_PATH))
        _load_indexed_repos()


def _save_index_to_disk():
    idx = _get_indexer()
    idx.save(str(_INDEX_PATH))


def _cache_context_result(key: str, result: dict):
    try:
        from kc_core.cache import cache_result
        cache_result(key, result, ttl=60)
    except Exception:
        pass


def _invalidate_cache():
    try:
        from kc_core.cache import clear_cache
        clear_cache("query:*")
    except Exception:
        pass


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
        from kc_core.cache import init as cache_init, is_available
        cache_init()
        if is_available():
            print("[leo-mcp] Redis cache conectado")
    except Exception:
        pass
    yield
    print("[leo-mcp] Apagando.")


app = FastAPI(title="Leo-Code MCP", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "leo-code-mcp", "version": "0.1.0"}


@app.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest, request: Request):
    """KC-RAG: indexer → Qdrant → compress → contexto comprimido."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")
    try:
        repo = os.path.abspath(req.repo_path)
        await _ensure_indexed(repo)

        cache_key = f"{req.query}|{repo}|{req.task_type}|{req.budget_tokens}"
        try:
            from kc_core.cache import get_cached_result
            cached = get_cached_result(cache_key)
            if cached:
                return ContextResponse(**cached)
        except Exception:
            pass

        idx = _get_indexer()
        all_caps = idx.get_capsules()
        # Filter to only capsules from this repo (prevents cross-repo contamination)
        repo_prefix = repo + os.sep
        caps = {
            k: v for k, v in all_caps.items()
            if os.path.abspath(v.file_path).startswith(repo_prefix) or
               os.path.abspath(v.file_path) == repo
        }
        vs = _get_vector_store(repo)

        from kc_code.kc_rag.classifier import classify_task, get_budget
        task_type = classify_task(req.query) if req.task_type == "auto" else req.task_type
        budget = get_budget(req.query) if req.budget_tokens <= 0 else req.budget_tokens

        # no_code: devolver documentos relevantes a la query (keyword match en contenido)
        if task_type == "no_code":
            from kc_code.kc_rag.compressor import compress
            query_lower = req.query.lower()
            stopwords = {"un", "una", "de", "del", "la", "el", "los", "las", "en", "con",
                         "para", "por", "que", "cual", "cuales", "como", "se", "su", "al",
                         "es", "y", "o", "a", "no", "si", "le", "lo", "me", "tu", "mi"}
            query_terms = [w for w in query_lower.split() if len(w) >= 4 and w not in stopwords]
            doc_caps = [
                c for c in caps.values()
                if c.type == "document" and any(
                    t in (c.content or "").lower() or t in (c.docstring or "").lower()
                    for t in query_terms
                )
            ]
            if not doc_caps:
                doc_caps = [c for c in caps.values() if c.type == "document"][:10]
            context = compress(doc_caps, list(caps.values()), budget_tokens=max(budget, 800), task_type=task_type)
            result = {"context": context, "tokens": len(context) // 2, "task_type": task_type, "capsules_total": len(caps)}
            _cache_context_result(cache_key, result)
            return ContextResponse(**result)

        # Hybrid: exact match (one rep per file for path, name match) + semantic
        query_words = set(re.findall(r"\w{4,}", req.query.lower()))
        # Expandir: "retrieve_subgraph" → {"retrieve_subgraph", "retrieve", "subgraph"}
        query_words = query_words | {
            part for w in query_words for part in w.split("_") if len(part) >= 4
        }

        # Detectar prefijos de directorio en la query: "query/", "src/", etc.
        dir_prefixes: set[str] = set()
        for match in re.findall(r"\b([\w_-]+)/", req.query):
            dir_prefixes.add(match.lower())

        def _dir_priority(c):
            if not dir_prefixes:
                return 0
            fp = (c.file_path or "").lower().replace("\\", "/")
            return 1 if any(f"/{d}/" in fp for d in dir_prefixes) else 0

        # Detect files named explicitly in query (e.g. "pipeline.py" → all capsules from that file)
        specific_file_paths: set[str] = set()
        for word in query_words:
            for c in caps.values():
                stem = Path(c.file_path).stem.lower()
                if word == stem or word == stem.replace("_", ""):
                    specific_file_paths.add(c.file_path)

        path_seen: set[str] = set()
        specific_match: list = []  # ALL capsules from explicitly-named files (highest priority)
        path_match: list = []      # one capsule per other path-matched file
        name_match: list = []
        for c in caps.values():
            fp = (c.file_path or "").lower().replace("\\", "/")
            nm = c.name.lower()
            if c.file_path in specific_file_paths:
                specific_match.append(c)
            elif any(w in fp for w in query_words):
                if c.file_path not in path_seen:
                    path_match.append(c)
                    path_seen.add(c.file_path)
            elif any(w in nm for w in query_words):
                name_match.append(c)
        # Sort specific_match: tier1=path-words, tier2=exact-name-match, tier3=name-substring
        # Tier2 ensures retrieve_subgraph beats graph.client.run_query when both have equal
        # path and substring scores (regex \w{4,} treats "retrieve_subgraph" as one token).
        specific_match.sort(
            key=lambda c: (
                -_dir_priority(c),
                -sum(1 for w in query_words if w in (c.file_path or "").lower().replace("\\", "/")),
                # Prefer actual defs (no dots, type is function/class) over imports and modules
                0 if (c.type in ("function", "class") and "." not in c.name) else 1,
                -sum(1 for w in query_words if w in c.name.lower()),
            ),
        )
        # specific_match first → guarantees target file content leads the context
        exact = specific_match[:20] + path_match[:5] + name_match[:3]
        exact_ids = {c.id for c in exact}

        top_ids = vs.search(req.query, top_k=15)
        semantic = [caps[rid] for rid in top_ids if rid in caps and rid not in exact_ids]

        cap = 30 if task_type == "search" else (25 if specific_file_paths else 15)
        top_caps = (exact + semantic)[:cap]

        from kc_code.kc_rag.compressor import compress
        context = compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type, dir_filter=dir_prefixes)

        result = {"context": context, "tokens": len(context) // 2, "task_type": task_type, "capsules_total": len(caps)}
        _cache_context_result(cache_key, result)
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
            repos_indexed=list(_indexed_repos),
        )
    s = idx.stats()
    return StatsResponse(
        total_capsules=s["total_capsules"],
        total_files=s["total_files"],
        by_type=s["by_type"],
        repos_indexed=list(_indexed_repos),
    )


def main():
    parser = argparse.ArgumentParser(description="Leo-Code MCP Server")
    parser.add_argument("--workers", type=int, default=1, help="Número de workers uvicorn (default 1)")
    parser.add_argument("--port", type=int, default=9898, help="Puerto (default 9898)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")
    args = parser.parse_args()

    print(f"[leo-mcp] Leo-Code MCP Server v0.1.0 (workers={args.workers})")
    print("[leo-mcp] Endpoints:")
    print(f"  GET  http://{args.host}:{args.port}/health")
    print(f"  POST http://{args.host}:{args.port}/context")
    print(f"  POST http://{args.host}:{args.port}/search")
    print(f"  POST http://{args.host}:{args.port}/index")
    print(f"  POST http://{args.host}:{args.port}/preindex")
    print(f"  GET  http://{args.host}:{args.port}/stats")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=args.workers)


if __name__ == "__main__":
    main()
