"""VectorStore: Qdrant local con búsqueda HNSW sobre embeddings de cápsulas."""

import logging
import os
from leo_code.core.parser import Capsule

log = logging.getLogger("leo")


class VectorStore:
    """Almacena y busca cápsulas por similitud semántica en Qdrant local."""

    def __init__(self, collection_name: str = "kc_code_capsules",
                 path: str = "./cache/qdrant", dim: int = 384,
                 use_process_id: bool = True):
        # Use process ID for concurrent access (tests/benchmark)
        if use_process_id and "_" not in collection_name:
            pid = os.getpid()
            self.collection_name = f"{collection_name}_{pid}"
        else:
            self.collection_name = collection_name
        self.path = path
        self.dim = dim
        self._client = None
        self._collection = None
        self._encoder = None

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            if self._storage_locked():
                # Otro proceso leo (otro MCP/CLI/test sobre el mismo repo) tiene el
                # storage: qdrant-local se quedaría BLOQUEADO para siempre en su file
                # lock. Degradamos a memoria (re-embebe, pero funciona) en vez de colgar.
                import sys
                print(f"[vector_store] {self.path} en uso por otro proceso leo; "
                      "usando indice semantico en memoria.", file=sys.stderr)
                log.warning(f"{self.path} en uso por otro proceso leo; usando indice semantico en memoria.")
                self._client = QdrantClient(location=":memory:")
            else:
                self._client = QdrantClient(path=self.path)
        return self._client

    def _storage_locked(self) -> bool:
        """True si el .lock de qdrant-local está cogido por OTRO proceso (chequeo
        no bloqueante). ponytail: hay una ventana de carrera entre chequear y crear
        el cliente; suficiente para el caso real (procesos concurrentes de larga vida)."""
        lock_path = os.path.join(self.path, ".lock")
        if not os.path.exists(lock_path):
            return False
        try:
            import portalocker
            with open(lock_path, "a") as f:
                portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
                portalocker.unlock(f)
            return False
        except Exception:
            return True

    @property
    def collection(self):
        if self._collection is None:
            from qdrant_client.models import Distance, VectorParams
            try:
                self.client.get_collection(self.collection_name)
            except Exception:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
                )
            self._collection = self.collection_name
        return self._collection

    @property
    def encoder(self):
        if self._encoder is None:
            from leo_code.rag.encoder import Encoder
            self._encoder = Encoder()
        return self._encoder

    def add(self, capsules: list[Capsule]):
        """Añade cápsulas al índice vectorial con embeddings en batch."""
        if not capsules:
            return
        from qdrant_client.models import PointStruct

        docs = []
        for c in capsules:
            doc = f"{c.name} {c.type}: {c.signature}"
            if c.docstring:
                doc += f" {c.docstring}"
            docs.append(doc)

        vecs = self.encoder.encode_batch(docs)

        points = [
            PointStruct(
                id=c.id,
                vector=vec,
                payload={"name": c.name, "type": c.type, "file_path": c.file_path,
                          "signature": c.signature, "docstring": c.docstring or ""},
            )
            for c, vec in zip(capsules, vecs)
        ]

        for i in range(0, len(points), 100):
            self.client.upsert(collection_name=self.collection, points=points[i:i+100])

    def search(self, query: str, top_k: int = 50) -> list[str]:
        """Busca top_k cápsulas más similares a la query. Retorna IDs."""
        vec = self.encoder.encode(query)
        results = self.client.query_points(
            collection_name=self.collection,
            query=vec,
            limit=top_k,
        )
        return [r.id for r in results.points]

    def count(self) -> int:
        try:
            info = self.client.get_collection(self.collection_name)
            return info.points_count
        except Exception:
            return 0
