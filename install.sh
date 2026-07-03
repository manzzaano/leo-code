#!/bin/sh
# leo-code installer (macOS/Linux) — mismo estilo que opencode:
#   curl -fsSL https://raw.githubusercontent.com/manzzaano/leo-code/main/install.sh | bash
# Instala uv si falta y luego leo-code como tool global (leo-code, leo-code tui,
# leo-code-mcp-stdio quedan en el PATH).
set -eu

if ! command -v uv >/dev/null 2>&1; then
    echo "▸ instalando uv (gestor de tools de Python)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # el instalador de uv deja el binario en ~/.local/bin
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "▸ instalando leo-code…"
# PyPI primero; si aún no está publicado, directo desde GitHub
uv tool install leo-code 2>/dev/null || \
    uv tool install --from git+https://github.com/manzzaano/leo-code.git leo-code

echo
echo "✓ listo. Prueba:"
echo "    leo-code tui        # cockpit (funciona sin API key: /trace /impact /guard …)"
echo "    leo-code            # agente CLI"
echo "    claude mcp add leo-code -- leo-code-mcp-stdio   # motor en Claude Code"
echo
echo "  Si 'leo-code' no se encuentra, abre una shell nueva (uv añade ~/.local/bin al PATH)."
