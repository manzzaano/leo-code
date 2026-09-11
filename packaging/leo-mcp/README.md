# leo-mcp

El motor de contexto de leo-code como **servidor MCP**: cualquier agente (Claude Code,
opencode, Cursor…) lo añade y obtiene dos cosas que ningún otro MCP da juntas:

1. **Contexto comprimido con la misma señal** (`get_context`) — el subgrafo AST
   relevante en vez de archivos enteros: **80-97% menos tokens por consulta**.
2. **Respuestas estructurales DETERMINISTAS con prueba** (`graph`, op:
   `where`/`who_calls`/`impact`/`trace`/`guard`) — del grafo de llamadas real,
   cada resultado citado `archivo:línea`. Cero LLM, cero alucinación. El grafo
   está verificado formalmente contra oráculos independientes (`ast` de Python
   y el compilador de TypeScript), gateado en CI — ver el repo principal para
   los números medidos de la última corrida.

## Instalar

Todavía no está publicado en PyPI — por ahora, desde el repo principal:

```bash
git clone https://github.com/manzzaano/leo-code.git
cd leo-code
pip install -e .
```

## Claude Code

```bash
claude mcp add leo-code -- python -m leo_code.server.mcp_server
```

o en `.mcp.json` del proyecto:

```json
{
  "mcpServers": {
    "leo-code": {
      "command": "python",
      "args": ["-m", "leo_code.server.mcp_server"],
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
      "command": ["python", "-m", "leo_code.server.mcp_server"],
      "enabled": true,
      "environment": { "LEO_REPO": "." }
    }
  }
}
```

## Tools

| Tool | Qué devuelve | LLM |
|---|---|---|
| `get_context` | Subgrafo de código comprimido para una consulta (80-97% menos tokens) | no |
| `graph` (op=`where`) | Todas las definiciones de un símbolo | no |
| `graph` (op=`who_calls`) | Llamadores directos de un símbolo, citados `archivo:línea` | no |
| `graph` (op=`impact`) | Cierre transitivo: todo lo que se rompe si cambias X | no |
| `graph` (op=`trace`) | Camino de llamadas A→B, incluso cross-archivo/repo/lenguaje | no |
| `graph` (op=`guard`) | Radio de explosión + qué afectados están SIN test (riesgo) antes de editar | no |

`LEO_REPO` (opcional): repo a precalentar al arrancar; cada tool acepta además
`repo_path` por llamada. El índice estructural está listo en segundos; el
embedding semántico sube en background sin bloquear.
