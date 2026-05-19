"""leo-code-mcp: KC-RAG sidecar server for Leo-Code.

Endpoints:
  GET  /health              — health check
  POST /context             — KC-RAG: indexer → Qdrant → compress → contexto
  POST /search              — Búsqueda semántica en el KG
  POST /index               — Indexar un repositorio
  GET  /stats               — Estadísticas del índice

Ejecutar: python -m leo_mcp.server  (puerto 9898)
         leo-code-mcp                (si instalado vía pip)
"""

import os
import re
import sys
import json
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Monorepo paths: sidecar/leo_mcp/server.py → leo-code/ → kc-rag/ + kc-core/
_ROOT = Path(__file__).parent.parent.parent  # leo-code/
sys.path.insert(0, str(_ROOT / "kc-rag"))
sys.path.insert(0, str(_ROOT / "kc-core"))

_indexer = None
_vector_store = None
_indexed_repos: set[str] = set()
_index_lock = threading.Lock()


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
    global _vector_store
    if _vector_store is None:
        from kc_code.kc_rag.vector_store import VectorStore
        _vector_store = VectorStore(
            collection_name=f"leo_mcp_{abs(hash(repo_path)) % 10000}",
            path="./cache/qdrant_leo",
        )
    return _vector_store


def _ensure_indexed(repo_path: str):
    global _indexed_repos
    with _index_lock:
        if repo_path not in _indexed_repos:
            idx = _get_indexer()
            idx.build(repo_path, languages=["python", "text"], verbose=False)
            vs = _get_vector_store(repo_path)
            vs.add(list(idx.get_capsules().values()))
            _indexed_repos.add(repo_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[leo-mcp] Arrancando servidor KC-RAG en puerto 9898...")
    yield
    print("[leo-mcp] Apagando.")


app = FastAPI(title="Leo-Code MCP", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "leo-code-mcp", "version": "0.1.0"}


@app.post("/context", response_model=ContextResponse)
async def get_context(req: ContextRequest):
    """KC-RAG: indexer → Qdrant → compress → contexto comprimido."""
    try:
        repo = os.path.abspath(req.repo_path)
        _ensure_indexed(repo)

        idx = _get_indexer()
        caps = idx.get_capsules()
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
            return ContextResponse(
                context=context,
                tokens=len(context) // 2,
                task_type=task_type,
                capsules_total=len(caps),
            )

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

        return ContextResponse(
            context=context,
            tokens=len(context) // 2,
            task_type=task_type,
            capsules_total=len(caps),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """Búsqueda semántica en el KG de código."""
    try:
        repo = os.path.abspath(req.repo_path)
        _ensure_indexed(repo)

        idx = _get_indexer()
        caps = idx.get_capsules()
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
        idx = _get_indexer()
        count = idx.build(repo, languages=langs, verbose=True)
        vs = _get_vector_store(repo)
        vs.add(list(idx.get_capsules().values()))
        _indexed_repos.add(repo)
        return {"status": "ok", "capsules": count, "repo": repo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """Estadísticas del índice actual."""
    idx = _get_indexer()
    s = idx.stats()
    return StatsResponse(
        total_capsules=s["total_capsules"],
        total_files=s["total_files"],
        by_type=s["by_type"],
        repos_indexed=list(_indexed_repos),
    )


def main():
    print("[leo-mcp] Leo-Code MCP Server v0.1.0")
    print("[leo-mcp] Endpoints:")
    print("  GET  http://localhost:9898/health")
    print("  POST http://localhost:9898/context")
    print("  POST http://localhost:9898/search")
    print("  POST http://localhost:9898/index")
    print("  GET  http://localhost:9898/stats")
    uvicorn.run(app, host="0.0.0.0", port=9898, log_level="info")


if __name__ == "__main__":
    main()
