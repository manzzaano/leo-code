"""Semantic clustering: organize capsules into coherent clusters with internal graph structure."""

from dataclasses import dataclass
from typing import Optional
import numpy as np
from sklearn.cluster import DBSCAN


@dataclass
class GraphEdge:
    """Edge in call graph between two capsules."""
    source_id: str
    target_id: str
    edge_type: str  # "calls", "imported_by", "inherits"


@dataclass
class ClusterNode:
    """Capsule within a semantic cluster."""
    capsule_id: str
    name: str
    type: str
    edges: list[GraphEdge]  # Outgoing edges within cluster


@dataclass
class SemanticCluster:
    """Semantic cluster with graph-organized capsules."""
    cluster_id: int
    label: str  # Inferred from capsules (e.g., "Framework Detection")
    capsules: list[ClusterNode]  # Root nodes in this cluster
    size: int  # Number of capsules


class SemanticClusterer:
    """Cluster capsules by semantic similarity, organize by graph."""

    def __init__(self, encoder):
        self.encoder = encoder
        self.clusters = []
        self.capsule_to_cluster = {}

    def cluster(self, capsules: list, embeddings: np.ndarray, min_samples: int = 2) -> list[SemanticCluster]:
        """Cluster capsules by semantic similarity.

        Args:
            capsules: List of Capsule objects
            embeddings: (n, 384) array of embeddings from encoder
            min_samples: DBSCAN min_samples parameter

        Returns:
            List of SemanticCluster with graph structure
        """
        if len(capsules) < 2:
            # Single capsule: create cluster with just it
            return [SemanticCluster(
                cluster_id=0,
                label=capsules[0].name if capsules else "Unknown",
                capsules=[ClusterNode(capsule_id=c.id, name=c.name, type=c.type, edges=[])
                          for c in capsules],
                size=len(capsules),
            )]

        # DBSCAN clustering (eps chosen for 384-dim embeddings, typically 0.3-0.5)
        clusterer = DBSCAN(eps=0.4, min_samples=min_samples, metric='cosine')
        labels = clusterer.fit_predict(embeddings)

        # Group capsules by cluster
        clusters_dict = {}
        for cap, label in zip(capsules, labels):
            if label == -1:  # Noise point: create singleton cluster
                label = max(clusters_dict.keys()) + 1 if clusters_dict else 0
            if label not in clusters_dict:
                clusters_dict[label] = []
            clusters_dict[label].append(cap)

        # Build clusters with graph structure
        result = []
        for cluster_id, cluster_caps in sorted(clusters_dict.items()):
            # Create cluster label from top capsules
            label = self._infer_label(cluster_caps)

            # Build graph: edges between capsules in this cluster
            capsule_ids_in_cluster = {c.id for c in cluster_caps}
            nodes = []
            for cap in cluster_caps:
                edges = []
                # Add outgoing edges (calls)
                for call in (cap.calls or []):
                    # Find if call target is in this cluster
                    for other_cap in cluster_caps:
                        if call in other_cap.name:
                            edges.append(GraphEdge(source_id=cap.id, target_id=other_cap.id, edge_type="calls"))
                            break
                # Add incoming edges (imported_by)
                for other_cap in cluster_caps:
                    if cap.name in (other_cap.calls or []):
                        edges.append(GraphEdge(source_id=other_cap.id, target_id=cap.id, edge_type="imported_by"))

                nodes.append(ClusterNode(capsule_id=cap.id, name=cap.name, type=cap.type, edges=edges))

            cluster = SemanticCluster(
                cluster_id=cluster_id,
                label=label,
                capsules=nodes,
                size=len(cluster_caps),
            )
            result.append(cluster)
            for cap in cluster_caps:
                self.capsule_to_cluster[cap.id] = cluster_id

        self.clusters = result
        return result

    def _infer_label(self, capsules: list) -> str:
        """Infer cluster label from capsule names/types."""
        # Simple heuristic: find common words in names
        if not capsules:
            return "Unknown"

        # Get common type
        types = [c.type for c in capsules]
        common_type = max(set(types), key=types.count) if types else "unknown"

        # Get first capsule's name as label (improve this heuristic)
        return f"{common_type.title()}: {capsules[0].name[:30]}"

    def get_cluster_context(self, capsule_id: str, depth: int = 1) -> SemanticCluster:
        """Get cluster containing this capsule, traversed to given depth."""
        cluster_id = self.capsule_to_cluster.get(capsule_id)
        if cluster_id is None or cluster_id >= len(self.clusters):
            return None

        return self.clusters[cluster_id]
