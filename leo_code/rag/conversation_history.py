"""Conversation history persistence: save/load compressed context per repo."""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone


class ConversationHistory:
    """Persist and retrieve conversation context across sessions."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self.history_dir = self.repo_path / ".leo-code" / "conversations"
        self.index_file = self.history_dir / "index.json"
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def _query_hash(self, query: str) -> str:
        """Generate hash for query to find related conversations."""
        return hashlib.md5(query.lower().encode()).hexdigest()[:8]

    def load_previous_contexts(self, query: str, limit: int = 3) -> dict:
        """Load compressed contexts from similar previous queries.

        Returns dict with keys: 'related_queries', 'accumulated_context'
        """
        if not self.index_file.exists():
            return {"related_queries": [], "accumulated_context": ""}

        try:
            index = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"related_queries": [], "accumulated_context": ""}

        # Find related queries (simple substring + hash matching)
        query_lower = query.lower()
        related = []

        for conv in index.get("conversations", []):
            q = conv.get("query", "").lower()
            # Match if shares keywords (very basic)
            common_words = set(q.split()) & set(query_lower.split())
            if common_words and len(common_words) >= 2:
                related.append(conv)

        # Sort by timestamp, take most recent
        related.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        related = related[:limit]

        # Accumulate contexts
        accumulated = ""
        for conv in related:
            if conv.get("compressed_context"):
                accumulated += f"\n--- Previous: {conv.get('query', 'N/A')} ---\n"
                accumulated += conv["compressed_context"]
                accumulated += "\n"

        return {
            "related_queries": [c.get("query", "") for c in related],
            "accumulated_context": accumulated,
        }

    def save_conversation(self, query: str, compressed_context: str, tokens: int, iterations: int):
        """Save query + compressed context to history."""
        conv_data = {
            "query": query,
            "query_hash": self._query_hash(query),
            "compressed_context": compressed_context,
            "tokens": tokens,
            "iterations": iterations,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Generate filename
        qhash = self._query_hash(query)
        conv_file = self.history_dir / f"conv_{qhash}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Save conversation
        conv_file.write_text(json.dumps(conv_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # Update index
        self._update_index(conv_data)

    def _update_index(self, conv_data: dict):
        """Update conversations index."""
        if self.index_file.exists():
            try:
                index = json.loads(self.index_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                index = {"conversations": []}
        else:
            index = {"conversations": []}

        # Add new entry (keep last 50)
        index["conversations"].append({
            "query": conv_data["query"],
            "query_hash": conv_data["query_hash"],
            "tokens": conv_data["tokens"],
            "iterations": conv_data["iterations"],
            "timestamp": conv_data["timestamp"],
        })
        index["conversations"] = index["conversations"][-50:]  # Keep last 50

        self.index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def clear_history(self):
        """Clear all conversation history for this repo."""
        if self.history_dir.exists():
            for f in self.history_dir.glob("conv_*.json"):
                f.unlink()
            if self.index_file.exists():
                self.index_file.unlink()
