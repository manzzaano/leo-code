"""Scorer sin embeddings: TF-IDF identifier-aware + PageRank estructural.

Reemplaza el ranking BM25 naive (`.lower().split()`) con dos señales combinadas:
- Estructural (40%): PageRank power-iteration sobre el call-graph (Capsule.calls).
- Semántica  (60%): TF-IDF coseno query↔(name + signature + docstring), con
  tokenización que parte snake_case/camelCase/PascalCase.
Las cápsulas de código reciben +0.3 sobre las de tipo documento.

La selección final usa un greedy knapsack con neighbor-decay: puntúa, coge el
mejor que cabe en el budget de tokens, y propaga un score decaído a los vecinos
del nodo seleccionado para explorar la vecindad relevante del subgrafo.

Algoritmos estándar reimplementados desde cero (sin numpy/networkx). Inspirado
en el enfoque de Slurp (token-budget-aware graph navigation).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from leo_code.core.parser import Capsule
from leo_code.core.tokens import count_tokens

_CAMEL_RUN = re.compile(r"([A-Z]+)([A-Z][a-z])")   # "XMLParser" -> "XML Parser"
_CAMEL_LU = re.compile(r"([a-z0-9])([A-Z])")        # "fooBar"    -> "foo Bar"
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Tokeniza partiendo snake_case/camelCase/PascalCase, preservando el compuesto.

    "recalcularPlayerStats" -> ["recalcular", "player", "stats", "recalcularplayerstats"]
    El identificador completo se conserva para que siga siendo buscable entero.
    """
    split = _CAMEL_RUN.sub(r"\1 \2", text)
    split = _CAMEL_LU.sub(r"\1 \2", split)
    primary = _WORD.findall(split.lower())
    seen = set(primary)
    extras = [t for t in _WORD.findall(text.lower()) if t not in seen]
    return primary + extras


def _capsule_text(c: Capsule) -> str:
    return f"{c.name} {c.signature or ''} {c.docstring or ''}"


def _build_adjacency(capsules: list[Capsule]) -> dict[str, set[str]]:
    """out[id] = set de ids llamados, resolviendo Capsule.calls (nombres) a ids."""
    by_name: dict[str, list[str]] = {}
    for c in capsules:
        by_name.setdefault(c.name, []).append(c.id)
    out: dict[str, set[str]] = {c.id: set() for c in capsules}
    for c in capsules:
        for callee in (c.calls or []):
            for tid in by_name.get(callee, []):
                if tid != c.id:
                    out[c.id].add(tid)
    return out


def pagerank(
    capsules: list[Capsule],
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> dict[str, float]:
    """PageRank power-iteration sobre el call-graph. Maneja dangling nodes.

    Los nodos sin aristas salientes redistribuyen su rank uniformemente
    (fórmula estándar de Google). Sin numpy.
    """
    ids = [c.id for c in capsules]
    N = len(ids)
    if N == 0:
        return {}

    out = _build_adjacency(capsules)
    out_deg = {i: len(out[i]) for i in ids}
    preds: dict[str, list[str]] = {i: [] for i in ids}
    for src, tgts in out.items():
        for t in tgts:
            preds[t].append(src)
    dangling = [i for i in ids if out_deg[i] == 0]

    rank = {i: 1.0 / N for i in ids}
    for _ in range(max_iter):
        prev = rank.copy()
        dangling_sum = alpha * sum(prev[i] for i in dangling) / N
        for i in ids:
            incoming = sum(prev[p] / out_deg[p] for p in preds[i])
            rank[i] = alpha * incoming + dangling_sum + (1.0 - alpha) / N
        if sum(abs(rank[i] - prev[i]) for i in ids) < N * tol:
            break
    return rank


def tfidf_scores(capsules: list[Capsule], query: str) -> dict[str, float]:
    """Coseno TF-IDF entre la query y el texto de cada cápsula (IDF suavizado)."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return {c.id: 0.0 for c in capsules}

    docs = {c.id: tokenize(_capsule_text(c)) for c in capsules}
    N = len(docs)

    # IDF solo para términos de la query (no construimos vocabulario completo).
    idf: dict[str, float] = {}
    for term in set(q_tokens):
        df = sum(1 for toks in docs.values() if term in set(toks))
        idf[term] = math.log((N + 1) / (df + 1)) + 1

    q_tf = Counter(q_tokens)
    q_vec = {t: (cnt / len(q_tokens)) * idf[t] for t, cnt in q_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values()))

    scores: dict[str, float] = {}
    for cid, toks in docs.items():
        if not toks or q_norm == 0.0:
            scores[cid] = 0.0
            continue
        d_tf = Counter(toks)
        d_vec = {t: (d_tf[t] / len(toks)) * idf[t] for t in idf if d_tf[t] > 0}
        d_norm = math.sqrt(sum(v * v for v in d_vec.values()))
        if d_norm == 0.0:
            scores[cid] = 0.0
        else:
            dot = sum(q_vec[t] * d_vec[t] for t in d_vec)
            scores[cid] = dot / (q_norm * d_norm)
    return scores


def score_capsules(
    capsules: list[Capsule],
    query: str,
    w_struct: float = 0.4,
    w_sem: float = 0.6,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Score combinado por id. Devuelve (final, structural, semantic) para --explain.

    final = w_struct·norm_pagerank + w_sem·tfidf; +0.3 (clamp 1.0) si no es documento.
    """
    if not capsules:
        return {}, {}, {}
    pr = pagerank(capsules)
    max_pr = max(pr.values()) if pr else 0.0
    pr_norm = {i: (v / max_pr if max_pr > 0.0 else 0.0) for i, v in pr.items()}
    tf = tfidf_scores(capsules, query)

    final: dict[str, float] = {}
    for c in capsules:
        s = w_struct * pr_norm.get(c.id, 0.0) + w_sem * tf.get(c.id, 0.0)
        if c.type != "document":
            s = min(1.0, s + 0.3)
        final[c.id] = s
    return final, pr_norm, tf


def _serialize(c: Capsule) -> str:
    parts = [c.id, c.name]
    if c.type:
        parts.append(f"({c.type})")
    if c.docstring:
        parts.append(c.docstring)
    if c.file_path:
        parts.append(f"-> {c.file_path}")
    return " ".join(p for p in parts if p)


def select_within_budget(
    capsules: list[Capsule],
    scores: dict[str, float],
    budget: int,
    neighbor_decay: float = 0.7,
    min_score: float = 0.0,
) -> tuple[list[Capsule], dict]:
    """Greedy knapsack con neighbor-decay, acotado a un budget de tokens.

    1. Pre-filtra cápsulas con score < min_score.
    2. Precomputa coste en tokens de cada candidata (cacheado por tiktoken).
    3. Coge la de mayor effective_score; si cabe en el budget restante, selecciona.
    4. Al seleccionar, propaga `score × neighbor_decay` a vecinos (pred+succ) no
       procesados si mejora su score actual.
    5. Para al agotar el budget o procesar todos los candidatos.

    Devuelve (cápsulas seleccionadas, stats).
    """
    total = len(capsules)
    empty = {
        "nodes_selected": 0, "nodes_total": total, "tokens_used": 0,
        "tokens_budget": budget, "coverage_pct": 0.0,
    }
    if total == 0 or budget <= 0:
        return [], empty

    by_id = {c.id: c for c in capsules}
    out = _build_adjacency(capsules)
    # vecindad no dirigida: la relevancia fluye en ambos sentidos del edge.
    neighbors: dict[str, set[str]] = {c.id: set() for c in capsules}
    for src, tgts in out.items():
        for t in tgts:
            neighbors[src].add(t)
            neighbors[t].add(src)

    token_cost = {c.id: count_tokens(_serialize(c)) for c in capsules}
    candidates = {c.id for c in capsules if scores.get(c.id, 0.0) >= min_score}
    effective = {i: scores.get(i, 0.0) for i in candidates}

    processed: set[str] = set()
    selected: list[str] = []
    used = 0

    while len(processed) < len(candidates):
        best = max(
            (i for i in candidates if i not in processed),
            key=lambda i: effective.get(i, 0.0),
        )
        processed.add(best)
        cost = token_cost[best]
        if cost <= budget - used:
            selected.append(best)
            used += cost
            boosted = effective.get(best, 0.0) * neighbor_decay
            for nbr in neighbors.get(best, ()):
                if nbr in candidates and nbr not in processed and boosted > effective.get(nbr, 0.0):
                    effective[nbr] = boosted
        if used >= budget:
            break

    stats = {
        "nodes_selected": len(selected), "nodes_total": total,
        "tokens_used": used, "tokens_budget": budget,
        "coverage_pct": round(len(selected) / total * 100, 1),
    }
    return [by_id[i] for i in selected], stats
