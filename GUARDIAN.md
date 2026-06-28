# leo-code guardian — garantía determinista de cambios

Todo agente GENERA código; ninguno PRUEBA que el cambio es seguro. El guardián sí,
porque tiene el grafo del código. **Determinista, con prueba citable, cero tokens de LLM.**

Por cada símbolo cambiado calcula:
- **Radio de explosión** — qué se rompe (cierre transitivo de llamadores), con `archivo:línea`.
- **Cross-lenguaje** — cruza el límite HTTP: cambiar un endpoint marca los componentes
  React/cliente que lo consumen (vía las aristas del boundary).
- **Cobertura** — qué afectados están cubiertos por tests y cuáles **NO** (riesgo).

Es justo lo que un revisor-LLM aluciona o se pierde.

## CLI

```bash
# ANTES de editar: ¿qué rompo si toco esto?
leo-code guardian -s compress

# PR: revisa el diff vs main, sale !=0 si hay afectados SIN test
leo-code guardian --base main

# pre-commit: solo lo staged
leo-code guardian --staged
```

Salida (ejemplo, cero LLM):
```
cambias `get_report`  [✗ SIN test]
  → afecta a 3 símbolos, 2 SIN test (riesgo)
    · Dashboard (component) @ web/app.tsx:14   [✗ SIN test]   ← rotura cross-lenguaje
    · render_page (function) @ views.py:88     [✓ test]
guardian · 1 cambios · 3 afectados · 2 SIN test (riesgo) — determinista, con prueba, cero LLM
```

## GitHub Action

Workflow incluido en `.github/workflows/guardian.yml`: en cada PR, indexa, revisa el
diff vs la base y **falla el check** si toca código cuyo radio de explosión no está
cubierto por tests — con el detalle y la prueba en el log. Cero coste de LLM.

## pre-commit

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: leo-guardian
      name: leo-code guardian (radio de explosión + cobertura)
      entry: leo-code guardian --staged
      language: system
      pass_filenames: false
```

## Vía MCP (para tu agente / Claude Code / opencode)

El servidor MCP expone la tool determinista **`guard`**: antes de que el agente edite un
símbolo, llama `guard <símbolo>` y recibe el radio de explosión + cobertura con prueba,
sin gastar tokens de LLM. Así el agente edita con red de seguridad.

```json
{ "mcpServers": { "leo-code": {
    "command": "python", "args": ["-m", "leo_code.server.mcp_server"] } } }
```
