# Packaging — dos productos OSS sobre un motor compartido

leo-code se publica como **dos productos** (`leo-code` agente · `leo-mcp` motor MCP)
sobre **`leo-code-core`** (el motor). El split es **real y construible**: los tres
`pyproject.toml` están en `packaging/` y producen tres wheels disjuntos.

```
leo-code-core   →  leo_code.engine + leo_code.core.* + leo_code.rag.{indexer, compressor,
                   vector_store, bm25, scorer, classifier, encoder}   (motor, SIN FastAPI)
   ├── leo-code  →  leo_code.rag.agent + leo_code.rag.cli + rag.llm + session/plugins/learning/sdk
   │               dep: leo-code-core · entrypoint: leo-code
   └── leo-mcp   →  leo_code.server (mcp_server + server http)
                   dep: leo-code-core, mcp · entrypoints: leo-code-mcp-stdio, leo-code-mcp
```

**Límite verificado:** `core`/`engine`/`rag`-motor **no importan** `rag.agent` ni `server`
(dependencia unidireccional). Los tres wheels son **disjuntos** y el `leo_code/__init__.py`
raíz lo provee solo el core → instalan en el mismo namespace sin conflicto.

## Construir los tres wheels

```bash
pip install build
for p in leo-code-core leo-code leo-mcp; do (cd packaging/$p && python -m build --wheel); done
# → packaging/<p>/dist/*.whl
```

## Instalar / desarrollar

```bash
# usuario del agente
pip install leo-code            # arrastra leo-code-core; comando: leo-code
# usuario del motor para su agente
pip install leo-mcp             # arrastra leo-code-core; comando: leo-code-mcp-stdio
```

Para desarrollo en el repo, `pip install -e .` (raíz) sigue dando un único paquete con
todos los entrypoints; el split en `packaging/` es para publicar por separado en PyPI.

> El `pyproject.toml` de la raíz se mantiene como instalación monolítica de desarrollo.
> Las versiones de los tres paquetes deben subirse juntas (todas `0.2.0` hoy).
