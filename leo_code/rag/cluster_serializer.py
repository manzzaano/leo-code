"""Serialize semantic clusters to hierarchical markdown."""

from leo_code.rag.semantic_clustering import SemanticCluster


def serialize_clusters(clusters: list[SemanticCluster], max_clusters: int = 5, max_nodes_per_cluster: int = 8) -> str:
    """Convert clusters to hierarchical markdown, limited by size.

    Args:
        clusters: List of SemanticCluster
        max_clusters: Limit to top N largest clusters
        max_nodes_per_cluster: Limit nodes per cluster

    Format:
    # Cluster: label
    ## Function: name (type)
    **Calls:** func1, func2
    **Called by:** func3
    ...
    """
    lines = []

    # Sort by cluster size (largest first) and take top N
    sorted_clusters = sorted(clusters, key=lambda c: c.size, reverse=True)[:max_clusters]

    for cluster in sorted_clusters:
        # Cluster header
        lines.append(f"# {cluster.label} ({cluster.size} items)")
        lines.append("")

        # Nodes within cluster (limit per cluster)
        for node in cluster.capsules[:max_nodes_per_cluster]:
            lines.append(f"## {node.name} ({node.type})")

            # Graph edges (limited)
            if node.edges:
                calls = [e.target_id for e in node.edges if e.edge_type == "calls"][:3]
                imported_by = [e.source_id for e in node.edges if e.edge_type == "imported_by"][:3]

                if calls:
                    lines.append(f"**Calls:** {', '.join(calls)}")
                if imported_by:
                    lines.append(f"**Imported by:** {', '.join(imported_by)}")

            lines.append("")

    return "\n".join(lines)
