"""Encoder: embedding de consultas. Usa MiniLM-L6 vía sentence-transformers."""

import threading


class Encoder:
    """Codifica texto a vector usando MiniLM (384-dim)."""

    # Un solo thread importa/carga a la vez: dos threads haciendo el primer
    # `from sentence_transformers import ...` a la vez se deadlockean en el
    # import lock en Windows (MCP colgado >3 min en el primer get_context).
    _load_lock = threading.Lock()

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            with Encoder._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()

    @property
    def dim(self) -> int:
        return 384
