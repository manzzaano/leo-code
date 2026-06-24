"""Conteo de tokens: tiktoken si está disponible, fallback heurístico ~4 chars/token.

Fuente única de verdad para presupuestar contexto. Antes el conteo estaba
disperso como `len(text) // 4` en varios sitios; centralizado aquí para que
el budget del retrieval (scorer) y el del agente usen la misma medida.
"""

from __future__ import annotations

import functools


@functools.lru_cache(maxsize=8)
def _enc(model: str):
    import tiktoken  # ponytail: dep opcional, import perezoso
    return tiktoken.get_encoding(model)


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Cuenta tokens. Usa tiktoken si está instalado; si no, ~4 chars/token."""
    if not text:
        return 0
    try:
        return len(_enc(model).encode(text))
    except Exception:
        # ponytail: tiktoken opcional; heurística suficiente para el budget
        return max(1, len(text) // 4)
