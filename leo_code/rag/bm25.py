"""BM25 Sparse Retrieval — complementa la búsqueda densa Qdrant con TF-IDF.

Indexa cápsulas como documentos: name + signature + docstring + nombre del archivo.
Usa rank_bm25 (Python puro, sin dependencias nativas).
"""

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
        try:
            from rank_bm25 import BM25Okapi
            self._index = BM25Okapi(self._tokenized)
        except ImportError:
            self._index = _SimpleBM25(self._tokenized)

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


class _SimpleBM25:
    """Fallback BM25 sin dependencias externas."""

    def __init__(self, corpus: list[list[str]]):
        self.corpus = corpus
        self.N = len(corpus)
        self.avgdl = sum(len(d) for d in corpus) / max(self.N, 1)
        self.idf: dict[str, float] = {}
        self._compute_idf()

    def _compute_idf(self):
        doc_freq: dict[str, int] = {}
        for doc in self.corpus:
            seen = set()
            for token in doc:
                if token not in seen:
                    doc_freq[token] = doc_freq.get(token, 0) + 1
                    seen.add(token)
        for token, df in doc_freq.items():
            self.idf[token] = __import__("math").log((self.N - df + 0.5) / (df + 0.5) + 1)

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        k1, b = 1.5, 0.75
        scores = [0.0] * self.N
        for token in query_tokens:
            idf = self.idf.get(token, 0)
            if idf == 0:
                continue
            for i, doc in enumerate(self.corpus):
                tf = doc.count(token)
                doc_len = len(doc)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * doc_len / max(self.avgdl, 1))
                scores[i] += idf * numerator / max(denominator, 0.001)
        return scores
