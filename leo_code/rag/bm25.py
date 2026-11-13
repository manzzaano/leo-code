"""BM25 Sparse Retrieval — complementa la búsqueda densa Qdrant con TF-IDF.

Indexa cápsulas como documentos: name + signature + docstring + nombre del archivo.
BM25Okapi propio (misma fórmula que rank_bm25, sin numpy: eran 43 MB de instalación).
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from leo_code.core.parser import Capsule


# Palabras de pregunta que no nombran código ("how does X work"): con ellas BM25 premiaba
# cualquier docstring en inglés.
_STOP = frozenset(
    "a an the is are was were be been to of in on at by for from with into about and or not "
    "how does do did what when where which why who whom this that these those it its can "
    "should would will there here".split())
_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def code_tokens(text: str) -> list[str]:
    """Palabras de texto e identificadores: parte snake_case y camelCase, minúsculas, sin
    palabras de pregunta y con un plural/-ing/-ed recortado ("callers" ~ "caller").

    Partir solo por espacios dejaba `discriminant_short_words(words:` como UN token: una
    pregunta en lenguaje natural no casaba nunca con un identificador compuesto.
    ponytail: stemmer de sufijos a mano, cambiar por uno real si el benchmark lo pide."""
    out = []
    for w in _WORD.findall(text or ""):
        w = w.lower()
        if w in _STOP:
            continue
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        else:
            for suf in ("ing", "ed", "s"):
                if w.endswith(suf) and len(w) - len(suf) >= 3 and not w.endswith("ss"):
                    w = w[:-len(suf)]
                    break
        out.append(w)
    return out


@dataclass
class BM25Result:
    capsule_id: str
    score: float
    name: str = ""
    file_path: str = ""


class BM25Index:
    def __init__(self):
        self._index = None
        self._ids: list[str] = []
        self._meta: dict[str, dict] = {}
        self._tokenized: list[list[str]] = []

    def add(self, capsules: list[Capsule]):
        docs = []
        for c in capsules:
            # Sin el cuerpo: medido en benchmark/nl_retrieval_bench.py, mete más ruido que señal.
            text = f"{c.name} {c.signature or ''} {c.docstring or ''} {Path(c.file_path or '').stem}"
            tokens = code_tokens(text)
            self._tokenized.append(tokens)
            self._ids.append(c.id)
            self._meta[c.id] = {"name": c.name, "file_path": c.file_path}
            docs.append(" ".join(tokens))
        self._index = _BM25Okapi(self._tokenized)

    def search(self, query: str, top_k: int = 20) -> list[BM25Result]:
        if self._index is None or not self._tokenized:
            return []
        tokens = code_tokens(query)
        if not tokens:
            return []
        scores = self._index.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [
            BM25Result(
                capsule_id=self._ids[i],
                score=float(s),
                name=self._meta.get(self._ids[i], {}).get("name", ""),
                file_path=self._meta.get(self._ids[i], {}).get("file_path", ""),
            )
            for i, s in ranked[:top_k] if s > 0
        ]


class _BM25Okapi:
    """BM25Okapi de rank_bm25 0.2.2 (Apache-2.0) sin numpy: misma idf con suelo
    epsilon * idf media y mismas operaciones en el mismo orden, así que las puntuaciones
    salen idénticas bit a bit (tests/test_bm25_okapi.py). Solo recorre los documentos
    que contienen cada término: los demás suman 0."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75,
                 epsilon: float = 0.25):
        self.k1, self.b = k1, b
        self.n = len(corpus)
        self.doc_len = [len(d) for d in corpus]
        self.avgdl = sum(self.doc_len) / max(self.n, 1)
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, doc in enumerate(corpus):
            freqs: dict[str, int] = {}
            for w in doc:
                freqs[w] = freqs.get(w, 0) + 1
            for w, f in freqs.items():
                self.postings.setdefault(w, []).append((i, f))
        self.idf: dict[str, float] = {}
        negative, idf_sum = [], 0.0
        for w, docs in self.postings.items():
            df = len(docs)
            self.idf[w] = idf = math.log(self.n - df + 0.5) - math.log(df + 0.5)
            idf_sum += idf  # a mano: sum() de 3.12 compensa y cambia el último bit
            if idf < 0:
                negative.append(w)
        eps = epsilon * (idf_sum / len(self.idf)) if self.idf else 0.0
        for w in negative:
            self.idf[w] = eps

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        k1, b, avgdl = self.k1, self.b, self.avgdl
        scores = [0.0] * self.n
        for q in query_tokens:
            idf = self.idf.get(q) or 0
            for i, f in self.postings.get(q, ()):
                scores[i] += idf * (f * (k1 + 1) / (f + k1 * (1 - b + b * self.doc_len[i] / avgdl)))
        return scores
