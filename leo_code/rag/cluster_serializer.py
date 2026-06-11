"""Serialize semantic clusters to hierarchical markdown."""

from leo_code.rag.semantic_clustering import SemanticCluster


def serialize_clusters(clusters: list[SemanticCluster]) -> str:
    """Convert clusters to hierarchical markdown.

    Format:
    # Cluster: label
    ## Function: name (type)
    **Calls:** func1, func2
    **Called by:** func3
    ...
    """
    lines = []

    for cluster in clusters:
        # Cluster header
        lines.append(f"# {cluster.label} ({cluster.size} items)")
        lines.append("")

        # Nodes within cluster
        for node in cluster.capsules:
            lines.append(f"## {node.name} ({node.type})")

            # Graph edges
            if node.edges:
                calls = [e.target_id for e in node.edges if e.edge_type == "calls"]
                imported_by = [e.source_id for e in node.edges if e.edge_type == "imported_by"]

                if calls:
                    lines.append(f"**Calls:** {', '.join(calls[:5])}")
                if imported_by:
                    lines.append(f"**Imported by:** {', '.join(imported_by[:5])}")

            lines.append("")

    return "\n".join(lines)
