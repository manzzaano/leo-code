"""Serialización markdown de contexto para enviar al LLM."""


def serialize_context(nodes: list[dict], edges: list[dict] = None) -> str:
    """
    Markdown format: readable to LLM, visual hierarchy.

    Format per entity:
    ## name (type)
    **File:** path
    **Signature:** function_signature
    **Doc:** brief description

    Relations at end if edges provided.
    """
    lines = []
    node_map = {n["id"]: n.get("name", n["id"]) for n in nodes}

    skip_keys = {
        "id", "status", "created_at", "updated_at", "source_doc_id", "source_hash",
        "aliases", "_depth", "precision_critical", "embedding",
    }

    # Campos objetivo: código (original) + dominio (nuevo)
    target_keys = {
        # Código
        "parametros", "lineas_aprox", "lineas", "module", "docstring", "tipo_retorno",
        "metodos_publicos", "metodos", "hereda_de", "file_path", "path", "importado_por", "confidence",
        "calls", "imports",
        # Dominio
        "descripcion", "description", "precio", "precio_base", "precio_final",
        "descuento", "descuento_pct", "porcentaje", "valor", "valor_maximo",
        "tipo_condicion", "aplica_a", "requisitos", "restricciones",
        "edad_minima", "edad_maxima", "penalizacion", "penalizacion_max",
        "servicios", "categoria", "segmento", "permanencia",
    }

    for node in nodes:
        name = node.get("name", node.get("id", "?"))
        ntype = node.get("type", "").upper() or "ENTITY"

        # Header
        lines.append(f"## {name} ({ntype})")
        lines.append("")

        # Props from properties dict + root fields
        props_source = node.get("properties", {}) or {}
        # "content" (cuerpo de código) se renderiza aparte en bloque, sin el
        # flatten/truncado a 120 chars genérico — si no, include_body=True
        # (debug/optimize/desambiguación) manda ~120 chars planos en vez del
        # cuerpo real.
        content_body = props_source.get("content")
        local_skip = skip_keys | {"content"}

        # Build ordered output
        for k in target_keys:
            # Try properties dict first, then root
            v = props_source.get(k) or node.get(k)
            if v and k not in local_skip:
                v_str = str(v).replace("\n", " ").strip()
                if len(v_str) > 120:
                    v_str = v_str[:117] + "..."
                # Format key name
                key_label = k.replace("_", " ").title()
                lines.append(f"**{key_label}:** {v_str}")

        # Any remaining props in properties dict
        for k, v in props_source.items():
            if v and k not in local_skip and k not in target_keys:
                v_str = str(v).replace("\n", " ").strip()
                if len(v_str) > 120:
                    v_str = v_str[:117] + "..."
                key_label = k.replace("_", " ").title()
                lines.append(f"**{key_label}:** {v_str}")

        if content_body:
            body_str = str(content_body)
            if len(body_str) > 2000:
                body_str = body_str[:2000] + "\n# ... [truncado]"
            lines.append("**Content:**")
            lines.append(f"```\n{body_str}\n```")

        lines.append("")  # Blank line between entities

    # Edges section
    if edges:
        lines.append("## Relations")
        lines.append("")
        for edge in edges:
            from_name = node_map.get(edge["from"], edge["from"][:12])
            to_name = node_map.get(edge["to"], edge["to"][:12])
            rel_type = edge.get("type", "RELATES")
            lines.append(f"- {from_name} **[{rel_type}]** {to_name}")

    return "\n".join(lines)
