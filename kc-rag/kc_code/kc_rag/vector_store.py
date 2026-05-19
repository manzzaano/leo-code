"""VectorStore: Qdrant local con búsqueda HNSW sobre embeddings de cápsulas."""

from kc_core.parser import Capsule


class VectorStore:
    """Almacena y busca cápsulas por similitud semántica en Qdrant local."""

    def __init__(self, collection_name: str = "kc_code_capsules",
                 path: str = "./cache/qdrant", dim: int = 384):
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
            self._client = QdrantClient(path=self.path)
        return self._client

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
            from kc_code.kc_rag.encoder import Encoder
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
