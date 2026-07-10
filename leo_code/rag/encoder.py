"""Encoder: embedding de consultas. Usa MiniLM-L6 vía sentence-transformers."""

import threading


class Encoder:
    """Codifica texto a vector usando MiniLM (384-dim)."""

    # Un solo thread importa/carga a la vez: dos threads haciendo el primer
    # `from sentence_transformers import ...` a la vez se deadlockean en el
    # import lock en Windows (MCP colgado >3 min en el primer get_context).
    _load_lock = threading.Lock()
    # Cargar los pesos tarda ~8-9s por proceso. is_warm() permite a los callers
    # (engine.compute_context) saltar la pata semántica mientras esté frío y
    # warm_bg() la calienta sin bloquear — a partir de ahí semántica normal.
    _warm = False
    _warm_started = False
    # Pesos compartidos por proceso (por nombre de modelo): warm_bg() los carga
    # una vez y TODAS las instancias (p.ej. la del VectorStore) los reusan.
    _shared: dict = {}

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name

    @property
    def model(self):
        m = Encoder._shared.get(self.model_name)
        if m is None:
            with Encoder._load_lock:
                m = Encoder._shared.get(self.model_name)
                if m is None:
                    from sentence_transformers import SentenceTransformer
                    m = SentenceTransformer(self.model_name)
                    Encoder._shared[self.model_name] = m
                    Encoder._warm = True
        return m

    @classmethod
    def is_warm(cls) -> bool:
        """True si algún Encoder de este proceso ya cargó los pesos."""
        return cls._warm

    @classmethod
    def warm_bg(cls):
        """Carga los pesos en un thread daemon (idempotente, no bloquea).
        Verificado en Windows: la carga en worker thread no deadlockea porque
        _load_lock serializa el primer import de sentence_transformers."""
        if cls._warm or cls._warm_started:
            return
        cls._warm_started = True
        threading.Thread(target=lambda: Encoder().model, daemon=True).start()

    def encode(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()

    @property
    def dim(self) -> int:
        return 384
