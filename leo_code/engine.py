"""leo-code-core — el MOTOR: indexado estructural + retrieval híbrido + compresión.

Núcleo compartido por los dos productos OSS, SIN dependencias de FastAPI ni del
agente: así `leo-code` (agente) y `leo-code-mcp` (servidor MCP) pueden empaquetarse
por separado dependiendo solo de este core.

API pública:
  - compute_context(repo, query, task_type, budget) -> dict   (KC-RAG: contexto comprimido)
  - _ensure_indexed(repo) / _do_index(repo)                    (indexado persistente)
  - _get_indexer() / _get_vector_store(repo) / _repo_caps()    (acceso al índice)
El cerebro determinista (queries estructurales con prueba) vive en core/graphquery.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_CACHE_DIR = Path(os.getenv("LEO_CACHE_DIR", "./cache"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_INDEX_PATH = _CACHE_DIR / "kc_index.json.gz"
_REPOS_PATH = _CACHE_DIR / "kc_indexed_repos.json"
_LOCK_PATH = _CACHE_DIR / "kc_index.lock"

_indexer = None
_vector_stores: dict[str, object] = {}
_indexed_repos: set[str] = set()
_index_lock = threading.Lock()
_index_executor = ThreadPoolExecutor(max_workers=1)
_bm25_stores: dict[str, object] = {}


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


def _get_indexer():
    global _indexer
    if _indexer is None:
        from leo_code.rag.indexer import Indexer
        _indexer = Indexer()
    return _indexer


_vs_lock = threading.Lock()


def _get_vector_store(repo_path: str):
    # Doble check con lock: dos threads (warmup MCP + primera tool) creaban DOS
    # clientes qdrant sobre el mismo storage → el segundo se queda bloqueado para
    # siempre en el file lock de qdrant-local (get_context colgado >3 min).
    if repo_path not in _vector_stores:
        with _vs_lock:
            if repo_path not in _vector_stores:
                from leo_code.rag.vector_store import VectorStore
                # Hash ESTABLE (no hash() salteado por proceso): mismo repo → misma colección
                # en disco entre reinicios → los embeddings se reusan en vez de re-embeber
                # las ~1400 cápsulas en cada arranque del server/MCP.
                stable = hashlib.md5(repo_path.encode("utf-8")).hexdigest()[:8]
                _vector_stores[repo_path] = VectorStore(
                    collection_name=f"leo_mcp_{stable}",
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
        from leo_code.core.cache import cache_result
        cache_result(key, result, ttl=60)
    except Exception:
        pass


def _invalidate_cache():
    try:
        from leo_code.core.cache import clear_cache
        clear_cache("query:*")
    except Exception:
        pass


def _get_bm25(repo: str, caps: dict) -> object:
    if repo not in _bm25_stores:
        from leo_code.rag.bm25 import BM25Index
        _bm25_stores[repo] = BM25Index()
        _bm25_stores[repo].add(list(caps.values()))
    return _bm25_stores[repo]


def compute_context(repo: str, query: str, task_type_in: str = "auto",
                    budget_tokens_in: int = 0) -> dict:
    """Retrieval híbrido (exact + Qdrant + BM25 + scorer → RRF) + compress.

    Núcleo compartido por el endpoint HTTP /context y el servidor MCP (stdio).
    El repo debe estar ya indexado (`await _ensure_indexed(repo)`) antes de llamar.
    Devuelve {context, tokens, task_type, capsules_total}.
    """
    idx = _get_indexer()
    all_caps = idx.get_capsules()
    repo_prefix = repo + os.sep
    caps = {
        k: v for k, v in all_caps.items()
        if os.path.abspath(v.file_path).startswith(repo_prefix) or
           os.path.abspath(v.file_path) == repo
    }
    vs = _get_vector_store(repo)

    from leo_code.rag.classifier import classify_task, get_budget
    from leo_code.rag.compressor import compress
    task_type = classify_task(query) if task_type_in == "auto" else task_type_in
    budget = get_budget(query) if budget_tokens_in <= 0 else budget_tokens_in

    # no_code: devolver documentos relevantes a la query (keyword match en contenido)
    if task_type == "no_code":
        query_lower = query.lower()
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
        return {"context": context, "tokens": len(context) // 2, "task_type": task_type, "capsules_total": len(caps)}

    # Hybrid: exact match (one rep per file for path, name match) + semantic
    query_words = set(re.findall(r"\w{4,}", query.lower()))
    # Expandir: "retrieve_subgraph" → {"retrieve_subgraph", "retrieve", "subgraph"}
    query_words = query_words | {
        part for w in query_words for part in w.split("_") if len(part) >= 4
    }

    # Detectar prefijos de directorio en la query: "query/", "src/", etc.
    dir_prefixes: set[str] = set()
    for match in re.findall(r"\b([\w_-]+)/", query):
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
    specific_match.sort(
        key=lambda c: (
            -_dir_priority(c),
            # El símbolo nombrado explícitamente lidera, AUNQUE sea método: si no,
            # la clase contenedora se come el slot de cuerpo y el símbolo
            # preguntado desaparece del contexto (recall = precisión perdida).
            0 if c.name.split(".")[-1].lower() in query_words else 1,
            -sum(1 for w in query_words if w in (c.file_path or "").lower().replace("\\", "/")),
            # Prefer actual defs (no dots, type is function/class) over imports and modules
            0 if (c.type in ("function", "class") and "." not in c.name) else 1,
            -sum(1 for w in query_words if w in c.name.lower()),
        ),
    )
    # specific_match first → guarantees target file content leads the context
    exact = specific_match[:20] + path_match[:5] + name_match[:3]
    exact_ids = {c.id for c in exact}

    top_ids = vs.search(query, top_k=15)
    semantic = [caps[rid] for rid in top_ids if rid in caps and rid not in exact_ids]

    # BM25 sparse search — complementa Qdrant para términos exactos
    bm25_results = []
    try:
        _bm25 = _get_bm25(repo, caps)
        bm25_results = _bm25.search(query, top_k=15)
    except Exception:
        pass

    # Scorer estructural (Fase 1): PageRank + TF-IDF identifier-aware sobre el
    # pool candidato → señal estructural que ni Qdrant ni BM25 aportan.
    scorer_ranked: list[str] = []
    try:
        from leo_code.rag.scorer import score_capsules
        pool_ids = list(dict.fromkeys(
            [c.id for c in exact]
            + [c.id for c in semantic]
            + [bm.capsule_id for bm in bm25_results if bm.capsule_id in caps]
        ))
        pool = [caps[i] for i in pool_ids if i in caps]
        if pool:
            scorer_final, _, _ = score_capsules(pool, query)
            scorer_ranked = sorted(scorer_final, key=scorer_final.get, reverse=True)
    except Exception:
        scorer_ranked = []

    # Reciprocal Rank Fusion (k=60)
    fused_scores: dict[str, float] = {}
    for rank, c in enumerate(exact):
        fused_scores[c.id] = fused_scores.get(c.id, 0) + 1 / (60 + rank + 1)
    for rank, c in enumerate(semantic):
        fused_scores[c.id] = fused_scores.get(c.id, 0) + 1 / (60 + rank + 1)
    for rank, bm in enumerate(bm25_results):
        if bm.capsule_id in caps:
            fused_scores[bm.capsule_id] = fused_scores.get(bm.capsule_id, 0) + 1 / (60 + rank + 1)
    for rank, cid in enumerate(scorer_ranked):
        fused_scores[cid] = fused_scores.get(cid, 0) + 1 / (60 + rank + 1)

    cap = 30 if task_type == "search" else (25 if specific_file_paths else 15)
    fused_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    top_caps = [caps[rid] for rid in fused_ids if rid in caps and rid not in exact_ids]
    top_caps = exact + top_caps
    top_caps = top_caps[:cap]

    context = compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type, dir_filter=dir_prefixes, query=query)
    return {"context": context, "tokens": len(context) // 2, "task_type": task_type, "capsules_total": len(caps)}
