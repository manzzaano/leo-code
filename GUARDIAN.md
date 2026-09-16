# python -m leo_code.core.guardian — garantía determinista de cambios

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
python -m leo_code.core.guardian -s compress

# PR: revisa el diff vs main, sale !=0 si hay afectados SIN test
python -m leo_code.core.guardian --base main

# pre-commit: solo lo staged
python -m leo_code.core.guardian --staged
```

Salida (ejemplo, cero LLM):
```
changing `get_report`  [✗ NO test]
  → affects 3 symbol(s), 2 with NO test (risk)
    · Dashboard (component) @ web/app.tsx:14   [✗ NO test]   ← rotura cross-lenguaje
    · render_page (function) @ views.py:88     [✓ tested]
guardian · 1 changed · 3 affected · 2 with NO test (risk) — deterministic, with proof, zero LLM
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
      name: python -m leo_code.core.guardian (radio de explosión + cobertura)
      entry: python -m leo_code.core.guardian --staged
      language: system
      pass_filenames: false
```

## Vía MCP (para tu agente / Claude Code / opencode)

El servidor MCP expone el guardián como **`graph` con `op=guard`**: antes de que el agente
edite un símbolo, llama `graph(op="guard", symbol="<símbolo>")` y recibe el radio de
explosión + cobertura con prueba, sin gastar tokens de LLM.

```bash
claude mcp add leo-mcp -- npx -y leo-mcp
```
