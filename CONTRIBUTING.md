# Contribuir a leo-code

leo-code es un fork de investigación de [opencode](https://github.com/sst/opencode) desarrollado por Ismael Manzano. El proyecto está en fase experimental activa.

## Qué tipo de cambios son bienvenidos

- Mejoras al sidecar KC-RAG (`leo-code-mcp/`)
- Mejoras al plugin de inyección de contexto (`packages/leo-code/src/context/`)
- Correcciones de bugs en el benchmark (`benchmark/`)
- Mejoras en la compresión adaptativa (`kc-code/kc_code/kc_rag/compressor.py`)
- Fixes heredados del upstream opencode (LSPs, providers, entornos)

## Qué NO se acepta sin diseño previo

- Cambios en la arquitectura core del agente (CLI, TUI, servidor)
- Nuevas características de producto sin consenso previo

## Cómo contribuir

1. Abre un issue describiendo el problema o mejora
2. Discute el enfoque antes de implementar
3. Crea un PR apuntando a la rama `main`

## Guía de estilo

Ver `AGENTS.md` para convenciones de código TypeScript.

Para Python (sidecar y benchmark): PEP 8, type hints opcionales, sin comentarios innecesarios.

## Repositorios relacionados

| Repo | Función |
|------|---------|
| [manzzaano/leo-code](https://github.com/manzzaano/leo-code) | CLI + plugin KC-RAG (este repo) |
| [manzzaano/leo-code-mcp](https://github.com/manzzaano/leo-code-mcp) | Sidecar FastAPI KC-RAG |
