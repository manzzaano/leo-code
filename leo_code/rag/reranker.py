"""Reranker: BGE cross-encoder rerankeando top-150 → top-15.

Más preciso que el bi-encoder inicial, evalúa consulta + cápsula juntas.
"""

from leo_code.core.parser import Capsule


class Reranker:
    """Rerankea cápsulas candidatas por relevancia conjunta consulta-cápsula."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        capsules: list[Capsule],
        top_k: int = 15,
    ) -> list[Capsule]:
        """Retorna las top_k cápsulas con mayor score de relevancia."""
        if not capsules:
            return []

        pairs = []
        for c in capsules:
            doc = f"{c.signature}"
            if c.docstring:
                doc += f" {c.docstring}"
            pairs.append([query, doc])

        scores = self.model.predict(pairs)
        ranked = sorted(zip(capsules, scores), key=lambda x: x[1], reverse=True)
        return [c for c, _ in ranked[:top_k]]
