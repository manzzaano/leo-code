# leo-mcp

El motor de contexto de leo-code como **servidor MCP**: cualquier agente (Claude Code,
opencode, Cursor…) lo añade y obtiene dos cosas que ningún otro MCP da juntas:

1. **Contexto comprimido con la misma señal** (`get_context`) — el subgrafo AST
   relevante en vez de archivos enteros: **~80% menos tokens**.
2. **Respuestas estructurales DETERMINISTAS con prueba** (`who_calls`, `impact`,
   `trace`, `where`, `guard`) — del grafo de llamadas real, cada resultado citado
   `archivo:línea`. Cero LLM, cero alucinación. El grafo está verificado al
   **100% de precisión y recall contra oráculos independientes** (`ast` de Python
   y el compilador de TypeScript) sobre repos reales de ~6M LOC, y esa verificación
   corre gateada en CI.

## Instalar

```bash
pip install leo-mcp        # (o desde este repo: pip install packaging/leo-code-core packaging/leo-mcp)
```

## Claude Code

Una línea:

```bash
claude mcp add leo-code -- leo-code-mcp-stdio
```

o en `.mcp.json` del proyecto:

```json
{
  "mcpServers": {
    "leo-code": {
      "command": "leo-code-mcp-stdio",
      "env": { "LEO_REPO": "." }
    }
  }
}
```

## opencode

En `opencode.json` (proyecto) u `~/.config/opencode/opencode.json` (global):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "leo-code": {
      "type": "local",
      "command": ["leo-code-mcp-stdio"],
      "enabled": true,
      "environment": { "LEO_REPO": "." }
    }
  }
}
```

## Tools

| Tool | Qué devuelve | LLM |
|---|---|---|
| `get_context` | Subgrafo de código comprimido para una consulta (~80% menos tokens) | no |
| `who_calls` | Llamadores directos de un símbolo, citados `archivo:línea` | no |
| `impact` | Cierre transitivo: TODO lo que se rompe si cambias X | no |
| `trace` | Camino de llamadas A→B, incluso cross-archivo/repo/lenguaje | no |
| `where` | Todas las definiciones de un símbolo | no |
| `guard` | Radio de explosión + qué afectados están SIN test (riesgo) antes de editar | no |

`LEO_REPO` (opcional): repo a precalentar al arrancar; cada tool acepta además
`repo_path` por llamada. El índice estructural está listo en segundos; el
embedding semántico sube en background sin bloquear.
