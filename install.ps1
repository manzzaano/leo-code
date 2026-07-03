# leo-code installer (Windows) — mismo estilo que opencode:
#   powershell -c "irm https://raw.githubusercontent.com/manzzaano/leo-code/main/install.ps1 | iex"
# Instala uv si falta y luego leo-code como tool global (leo-code, leo-code tui,
# leo-code-mcp-stdio quedan en el PATH).
$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "▸ instalando uv (gestor de tools de Python)…"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "▸ instalando leo-code…"
# PyPI primero; si aún no está publicado, directo desde GitHub
try {
    uv tool install leo-code
} catch {
    uv tool install --from git+https://github.com/manzzaano/leo-code.git leo-code
}

Write-Host ""
Write-Host "✓ listo. Prueba:"
Write-Host "    leo-code tui        # cockpit (funciona sin API key: /trace /impact /guard …)"
Write-Host "    leo-code            # agente CLI"
Write-Host "    claude mcp add leo-code -- leo-code-mcp-stdio   # motor en Claude Code"
Write-Host ""
Write-Host "  Si 'leo-code' no se encuentra, abre una terminal nueva (uv añade %USERPROFILE%\.local\bin al PATH)."
