"""SDK: Cliente Python para usar KC-RAG programáticamente.

Uso:
    from leo_code.sdk import KCRAGClient
    client = KCRAGClient("http://localhost:9898")
    ctx = client.context("qué hace la función process_payment", "./mi-repo")
    print(ctx.context)
"""

from dataclasses import dataclass
from typing import Optional
import httpx


@dataclass
class ContextResult:
    context: str
    tokens: int
    task_type: str
    capsules_total: int

@dataclass
class SearchResult:
    results: list[dict]
    total_capsules: int

@dataclass
class IndexResult:
    status: str
    capsules: int
    repo: str


class KCRAGClient:
    """Cliente HTTP para el sidecar KC-RAG."""

    def __init__(self, base_url: str = "http://localhost:9898", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    def context(self, query: str, repo_path: str = ".",
                task_type: str = "auto", budget_tokens: int = 0) -> ContextResult:
        """Obtiene contexto KC-RAG comprimido para una query."""
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/context", json={
                "query": query,
                "repo_path": repo_path,
                "task_type": task_type,
                "budget_tokens": budget_tokens,
            })
            r.raise_for_status()
            data = r.json()
            return ContextResult(
                context=data["context"],
                tokens=data["tokens"],
                task_type=data["task_type"],
                capsules_total=data["capsules_total"],
            )

    def search(self, query: str, repo_path: str = ".", top_k: int = 10) -> SearchResult:
        """Búsqueda semántica en el índice."""
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/search", json={
                "query": query,
                "repo_path": repo_path,
                "top_k": top_k,
            })
            r.raise_for_status()
            data = r.json()
            return SearchResult(
                results=data["results"],
                total_capsules=data["total_capsules"],
            )

    def index(self, repo_path: str, languages: str = "python,text") -> IndexResult:
        """Indexa un repositorio."""
        with httpx.Client(timeout=300) as client:
            r = client.post(f"{self.base_url}/index", json={
                "repo_path": repo_path,
                "languages": languages,
            })
            r.raise_for_status()
            data = r.json()
            return IndexResult(
                status=data["status"],
                capsules=data["capsules"],
                repo=data["repo"],
            )

    def preindex(self, repo_path: str, languages: str = "python,text") -> dict:
        """Pre-indexa en background."""
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/preindex", json={
                "repo_path": repo_path,
                "languages": languages,
            })
            r.raise_for_status()
            return r.json()

    def stats(self, repo_path: Optional[str] = None) -> dict:
        """Estadísticas del índice."""
        with httpx.Client(timeout=self.timeout) as client:
            params = {}
            if repo_path:
                params["repo_path"] = repo_path
            r = client.get(f"{self.base_url}/stats", params=params)
            r.raise_for_status()
            return r.json()


# Convenience: auto-connect al sidecar local
def connect(base_url: str = "http://localhost:9898") -> KCRAGClient:
    """Crea un cliente y verifica que el sidecar esté vivo."""
    c = KCRAGClient(base_url)
    c.health()
    return c
