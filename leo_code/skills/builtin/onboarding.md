---
name: onboarding
description: Onboarding a nuevos desarrolladores — entender la arquitectura del proyecto
version: "1.0"
triggers:
  - "cómo funciona"
  - "explicame el proyecto"
  - "estructura"
  - "arquitectura"
  - "onboarding"
  - "getting started"
  - "overview"
  - "guía"
task_types:
  - onboard
priority: 7
---

# Onboarding

Ayudas a nuevos desarrolladores a entender el proyecto rápidamente.

## Estructura de tu respuesta

### 1. Arquitectura general (un párrafo)
Qué hace el proyecto, en 2-3 frases. Tecnologías principales.  

### 2. Estructura de directorios
```
src/           → código fuente principal
  models/      → modelos de datos
  services/    → lógica de negocio
  api/         → endpoints HTTP/GraphQL
tests/         → tests
docs/          → documentación
```

### 3. Entrypoints
- Cómo se arranca el proyecto
- Scripts en package.json / pyproject.toml / Makefile
- Endpoints principales

### 4. Flujo de datos
- Request → Controller → Service → Repository → Database
- O el patrón que use el proyecto

### 5. Dónde empezar
- Los 3 archivos más importantes para entender el proyecto
- El test más simple para ver cómo se prueba
- La PR más pequeña posible para contribuir

## Reglas

- Sé conciso. El objetivo es que en 2 minutos sepan dónde están parados
- Usa nombres de archivo reales del repo, no genéricos
- Si hay ADRs (docs/adr/), menciónalas
- Si no encuentras algo, dilo ("No encontré tests", "No hay documentación de API")
