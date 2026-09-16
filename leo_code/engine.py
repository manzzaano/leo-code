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
import importlib.util
import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _default_cache_dir() -> Path:
    """Caché por usuario, FUERA del repo: el proyecto del usuario no se ensucia."""
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "leo-mcp" / "cache"
    return Path(os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache") / "leo-mcp"


_CACHE_DIR = Path(os.getenv("LEO_CACHE_DIR") or _default_cache_dir())
_INDEX_PATH = _CACHE_DIR / "kc_index.json.gz"
_REPOS_PATH = _CACHE_DIR / "kc_indexed_repos.json"
_LOCK_PATH = _CACHE_DIR / "kc_index.lock"

_indexer = None
_vector_stores: dict[str, object] = {}
_indexed_repos: set[str] = set()
_index_lock = threading.Lock()
_index_executor = ThreadPoolExecutor(max_workers=1)
_bm25_stores: dict[str, object] = {}


_STALE_LOCK_SECONDS = 120  # ningun build/sync real tarda esto — si el lock ya
                            # existia mas viejo que esto, es de un proceso muerto.


def _acquire_file_lock(timeout: int = 30) -> bool:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    start = time.time()
    while True:
        try:
            _LOCK_PATH.mkdir()
            return True
        except FileExistsError:
            try:
                if time.time() - _LOCK_PATH.stat().st_mtime > _STALE_LOCK_SECONDS:
                    _LOCK_PATH.rmdir()  # lock huerfano de un proceso que murio sin liberarlo
                    continue
            except OSError:
                pass
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
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _REPOS_PATH.write_text(json.dumps(sorted(_indexed_repos)), encoding="utf-8")


def _get_indexer():
    global _indexer
    if _indexer is None:
        from leo_code.rag.indexer import Indexer
        _indexer = Indexer(hygiene=True, max_file_kb=int(os.getenv("LEO_MAX_FILE_KB", "512")))
    return _indexer


_vs_lock = threading.Lock()


# Recall semántico = extra opcional (`leo-mcp[semantic]`: sentence-transformers +
# qdrant, ~2 GB con torch). Sin él el retrieval es exact + BM25 + scorer estructural
# y `graph` no cambia. LEO_SEMANTIC=0 lo apaga aunque esté instalado.
SEMANTIC = (os.getenv("LEO_SEMANTIC", "1") != "0"
            and all(importlib.util.find_spec(m) for m in ("sentence_transformers", "qdrant_client")))


class _NoVectorStore:
    """Vector store nulo: la semántica no está instalada o está apagada."""
    def add(self, capsules):
        pass

    def search(self, query, top_k=50):
        return []

    def count(self):
        return 0


_NO_VECTOR_STORE = _NoVectorStore()


def _get_vector_store(repo_path: str):
    if not SEMANTIC:
        return _NO_VECTOR_STORE
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
                    path=os.environ.get("LEO_QDRANT_PATH") or str(_CACHE_DIR / "qdrant"),
                    # El hash estable YA identifica el repo; el aislamiento entre
                    # procesos concurrentes lo da LEO_QDRANT_PATH (por directorio),
                    # no un sufijo de PID en el nombre de coleccion — con PID cada
                    # reinicio/subproceso pierde los embeddings ya calculados.
                    use_process_id=False,
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


_structural_at: dict[str, float] = {}  # repo -> monotonic del último load/build/sync
_generation: dict[str, int] = {}       # repo -> sube cuando cambian sus cápsulas (clave de caché)
_RESYNC_S = 5.0  # ponytail: resync por walk como mucho cada 5 s; watcher de FS si el walk pesa en monorepos


# Sube cuando cambia lo que el parser extrae (nuevas cápsulas, nuevas aristas): el índice
# en disco se re-parsea solo por mtime, así que sin esto una caché vieja seguiría sirviendo
# símbolos del parser anterior para siempre (p.ej. sin arrow functions ni atributos de clase).
_INDEX_FORMAT = 2


def repo_index_path(repo: str) -> Path:
    """Índice estructural de UN repo en la caché de usuario (varios proyectos abiertos
    a la vez no se pisan: cada server guarda solo su repo)."""
    h = hashlib.md5(repo.encode("utf-8")).hexdigest()[:8]
    return _CACHE_DIR / "repos" / f"{Path(repo).name}-{h}" / f"index-v{_INDEX_FORMAT}.json.gz"


def generation(repo: str) -> int:
    return _generation.get(repo, 0)


def ensure_structural(repo: str) -> dict | None:
    """Índice estructural (AST, sin embeddings) de `repo` listo y al día: lo único que
    necesitan `graph` y el retrieval estructural.

    1ª vez: build completo y se persiste. Arranques siguientes: load + sync incremental
    (solo lo cambiado). Durante la sesión: re-sync como mucho cada _RESYNC_S, para que
    las ediciones del agente se vean en el grafo.
    Devuelve {action, seconds, capsules, by_language} si cargó o cambió algo; None si
    ya estaba fresco.
    """
    with _index_lock:
        last = _structural_at.get(repo)
        if last is not None and time.monotonic() - last < _RESYNC_S:
            return None
        idx = _get_indexer()
        path = repo_index_path(repo)
        t0 = time.perf_counter()
        action = "sync"
        if last is None and path.exists():
            try:
                idx.load(str(path), merge=True)
                action = "load"
            except Exception:
                path.unlink(missing_ok=True)  # caché corrupta → rebuild
        if path.exists():
            s = idx.sync(repo, since_mtime=path.stat().st_mtime)
            changed = bool(s["reparsed_capsules"] or s["removed"])
        else:
            idx.build(repo)
            action, changed = "build", True
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            idx.save(str(path), repo=repo)
        if changed or last is None:
            _generation[repo] = _generation.get(repo, 0) + 1
        _structural_at[repo] = time.monotonic()
        if last is not None and not changed:
            return None
        caps = _repo_caps(idx, repo)
        return {"action": action, "seconds": round(time.perf_counter() - t0, 2),
                "capsules": len(caps), "by_language": dict(Counter(c.language for c in caps).most_common())}


async def _ensure_indexed(repo_path: str):
    global _indexed_repos
    repo = os.path.abspath(repo_path)
    with _index_lock:
        if repo in _indexed_repos:
            return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_index_executor, _do_index, repo)


def _index_once(repo: str, languages: list[str] | None, verbose: bool) -> int:
    """Indexa `repo` reusando lo que ya haya en disco/memoria cuando se pueda:
    - cache en disco fresco + vector store ya poblado -> no hace nada.
    - cache en disco pero obsoleto -> sync incremental (solo lo cambiado).
    - sin cache -> build() completo (primera vez).
    Devuelve el conteo de capsulas del repo tras indexar."""
    from leo_code.rag.indexer.staleness import is_cache_stale
    idx = _get_indexer()
    langs = languages or ["python", "text"]
    vs = _get_vector_store(repo)
    already = repo in _indexed_repos and _INDEX_PATH.exists()

    if already and not is_cache_stale(_INDEX_PATH, repo) and vs.count() > 0:
        return len(_repo_caps(idx, repo))

    if already:
        stats = idx.sync(repo, since_mtime=_INDEX_PATH.stat().st_mtime, languages=langs)
        delta = stats.get("capsules") or []
        if delta:
            vs.add(delta)
        return len(_repo_caps(idx, repo))

    count = idx.build(repo, languages=langs, verbose=verbose)
    vs.add(_repo_caps(idx, repo))
    return count


def _do_index(repo: str, languages: list[str] | None = None, verbose: bool = False) -> int:
    """Ejecuta la indexación (bloqueante). Se llama desde run_in_executor o /index."""
    global _indexed_repos
    if _acquire_file_lock():
        try:
            _load_index_from_disk()
            count = _index_once(repo, languages, verbose)
            _indexed_repos.add(repo)
            _save_index_to_disk()
            _save_indexed_repos()
            return count
        finally:
            _release_file_lock()
    # Fallback without lock
    count = _index_once(repo, languages, verbose)
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
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
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


# Palabras funcionales de 2-3 letras (EN/ES): no son señal. "cv", "db", "api", "get" sí lo son.
_SHORT_MAX_FILES = 2   # una sigla que aparece en 3+ archivos no señala nada concreto
_SHORT_STOP = {"the", "and", "for", "how", "why", "who", "are", "was", "its", "out", "our",
               "you", "all", "can", "but", "not", "has", "had", "did", "any", "may", "one",
               "del", "las", "los", "que", "por", "con", "una", "uno", "sus", "sin", "mas",
               "muy", "hay", "ser", "est", "este", "esta", "como", "dos"}


def discriminant_short_words(short_words: set[str], caps: dict) -> set[str]:
    """Siglas que DE VERDAD señalan un archivo: la sigla debe estar en el NOMBRE del archivo.

    Medido en NEXUS: por partes de nombre de símbolo, "cv" casa con 5 archivos y "run" con 3
    —la cardinalidad no los separa—, pero por stem de archivo "cv" → cv_morpher.py y
    "run"/"tab"/"job" → ninguno. Sin este filtro, "run" arrastraba alembic/env.py al frente
    con la prioridad máxima de specific_match.
    """
    if not short_words:
        return set()
    stems: dict[str, set] = {}
    for c in caps.values():
        stem = Path(c.file_path or "").stem.lower()
        for w in short_words & set(re.split(r"[_\-.]", stem)):
            stems.setdefault(w, set()).add(stem)
    return {w for w in short_words if 0 < len(stems.get(w, ())) <= _SHORT_MAX_FILES}


def _name_parts(name: str) -> set[str]:
    """Partes de un símbolo: snake_case y camelCase ('CVMorpher' → {cv, morpher})."""
    out = set()
    for chunk in re.split(r"[_\-.]", name or ""):
        out.update(p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", chunk))
    return out


def _get_bm25(repo: str, caps: dict) -> object:
    # Clave = generación del índice estructural: tras un resync (el agente editó código)
    # BM25 se reconstruye; antes se quedaba con los símbolos del arranque.
    gen = generation(repo)
    hit = _bm25_stores.get(repo)
    if hit is None or hit[0] != gen:
        from leo_code.rag.bm25 import BM25Index
        index = BM25Index()
        index.add(list(caps.values()))
        _bm25_stores[repo] = (gen, index)  # solo tras construirse: un add colgado/fallido no deja un índice vacío
    return _bm25_stores[repo][1]


def compute_context(repo: str, query: str, task_type_in: str = "auto",
                    budget_tokens_in: int = 0, self_sufficient: bool = False) -> dict:
    """Retrieval híbrido (exact + Qdrant + BM25 + scorer → RRF) + compress.

    Núcleo compartido por el endpoint HTTP /context y el servidor MCP (stdio).
    El repo debe estar ya indexado (`await _ensure_indexed(repo)`) antes de llamar.
    Devuelve {context, tokens, task_type, capsules_total}.

    self_sufficient (vía MCP): contexto con cuerpos completos y presupuesto ×4 —
    el cliente genérico no tiene tools de seguimiento y si le falta algo relee
    archivos enteros (doble coste medido en benchmark).
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

    from leo_code.rag.classifier import classify_task, TOKEN_BUDGET
    from leo_code.rag.compressor import compress
    task_type = classify_task(query) if task_type_in == "auto" else task_type_in
    # Presupuesto por el task_type EFECTIVO (forzado incluido). get_budget() reclasifica
    # la query por su cuenta: con task_type forzado a code_query y query corta en inglés
    # daba no_code → presupuesto 0 → contexto VACÍO al cliente MCP.
    budget = budget_tokens_in if budget_tokens_in > 0 else TOKEN_BUDGET.get(task_type, 1500)
    # self_sufficient ya NO multiplica el presupuesto: medido en c5b, la respuesta
    # x4 no sustituia la exploracion sino que la cebaba (tareas con get_context
    # +128% mediana; sin el, +1%). Cuerpos si, grasa no.

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
    # Siglas y palabras cortas ("CV", "db", "ws"): el corte en 4 las tiraba y "How does CV
    # tailoring work?" no casaba con cv_morpher.py (medido en NEXUS: el contexto lo lideraba
    # pdf_factory, código muerto). Solo cuentan como PARTE completa de un nombre/stem, nunca
    # como subcadena, para no reintroducir ruido.
    short_words = {w for w in re.findall(r"[a-z0-9]{2,3}", query.lower()) if w not in _SHORT_STOP}
    # ...y solo si DISCRIMINAN: "cv" señala un archivo (cv_morpher.py), pero "run" o "tab"
    # aparecen en medio repo y, con la prioridad máxima de specific_match, arrastraban
    # archivos irrelevantes (medido en NEXUS: la pregunta del Mentor abría con alembic/env.py).
    short_words = discriminant_short_words(short_words, caps)
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
    for c in caps.values():
        stem = Path(c.file_path).stem.lower()
        parts = set(re.split(r"[_\-.]", stem))
        if any(w == stem or w == stem.replace("_", "") for w in query_words) or (short_words & parts):
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
        elif any(w in nm for w in query_words) or (short_words & _name_parts(c.name)):
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

    # Fast start: cargar el encoder cuesta ~9s por proceso. Con el encoder frío,
    # esta query sirve solo con las patas estructurales (exact + BM25 + scorer,
    # instantáneas) y el encoder se calienta en background para las siguientes.
    # LEO_FAST_START=0 restaura el comportamiento bloqueante (esperar semántica).
    top_ids: list = []
    if SEMANTIC:
        from leo_code.rag.encoder import Encoder
        if Encoder.is_warm() or os.getenv("LEO_FAST_START", "1") == "0":
            top_ids = vs.search(query, top_k=15)
        else:
            Encoder.warm_bg()
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

    context = compress(top_caps, list(caps.values()), budget_tokens=budget, task_type=task_type, dir_filter=dir_prefixes, query=query, self_sufficient=self_sufficient)
    return {"context": context, "tokens": len(context) // 2, "task_type": task_type, "capsules_total": len(caps)}
