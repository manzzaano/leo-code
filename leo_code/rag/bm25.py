"""BM25 Sparse Retrieval — complementa la búsqueda densa Qdrant con TF-IDF.

Indexa cápsulas como documentos: name + signature + docstring.
Usa rank_bm25 (Python puro, sin dependencias nativas).
"""

from dataclasses import dataclass, field

from leo_code.core.parser import Capsule


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
            text = f"{c.name} {c.signature or ''} {c.docstring or ''}"
            tokens = text.lower().split()
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
        tokens = query.lower().split()
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
