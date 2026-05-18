"""Encoder: embedding de consultas. Usa MiniLM-L6 vía sentence-transformers,
con fallback TF-IDF ligero si no está disponible."""


class Encoder:
    """Codifica texto a vector usando MiniLM (384-dim) o TF-IDF como fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._tfidf_vectorizer = None
        self._use_tfidf = False

    @property
    def model(self):
        if self._model is None and not self._use_tfidf:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception:
                self._use_tfidf = True
        return self._model

    def encode(self, text: str) -> list[float]:
        if self._model is not None:
            return self.model.encode(text).tolist()
        return self._tfidf_encode(text)

    def _tfidf_encode(self, text: str) -> list[float]:
        from sklearn.feature_extraction.text import TfidfVectorizer
        if self._tfidf_vectorizer is None:
            self._tfidf_vectorizer = TfidfVectorizer(max_features=384)
            self._tfidf_vectorizer.fit([text])
        vec = self._tfidf_vectorizer.transform([text]).toarray()[0]
        return vec.tolist() + [0.0] * (384 - len(vec))

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if self._model is not None:
            return self.model.encode(texts).tolist()
        return [self._tfidf_encode(t) for t in texts]

    @property
    def dim(self) -> int:
        return 384
