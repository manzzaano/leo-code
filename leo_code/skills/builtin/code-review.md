---
name: code-review
description: Code review profesional con checklist de calidad, SOLID, y buenas prácticas
version: "1.0"
triggers:
  - "code review"
  - "review"
  - "revisa"
  - "revisar"
  - "revisión"
  - "quality"
task_types:
  - review
file_extensions:
  - py
  - ts
  - js
  - go
  - rs
  - java
priority: 8
---

# Code Review

Haces code review profesional. Evalúa cada archivo contra este checklist.

## Checklist

### Corrección
- ¿Maneja todos los casos de error? (input inválido, nil/None, timeout, excepciones)
- ¿Hay race conditions? (goroutines, threads, async sin locks)
- ¿Los recursos se liberan? (files, connections, locks)

### Diseño
- **SOLID**: ¿Single responsibility? ¿Open/closed? ¿Dependency inversion?
- ¿La función hace UNA sola cosa? Si tiene "and" en el nombre, sepárala
- ¿Demasiados parámetros? (>4 suele indicar que falta una struct/clase)
- ¿La interfaz es más simple que la implementación? (depth > 0)

### Legibilidad
- Nombres descriptivos: `process_payment` no `do_stuff`
- Sin números mágicos: usa constantes con nombre
- Comentarios explican POR QUÉ, no QUÉ (el código ya dice qué)
- Early returns en vez de anidar if/else

### Testing
- ¿Los cambios incluyen tests?
- ¿Los tests cubren casos de error, no solo happy path?
- ¿Los tests son independientes entre sí?

### Seguridad
- ¿Input validado y sanitizado?
- ¿SQL injection? Usa parámetros, no concatenación
- ¿Secrets hardcodeados? Usa env vars
- ¿Path traversal? Sanitiza file paths

### Formato de respuesta

Para cada archivo revisado, usa este formato:

```
**{archivo}** — {veredicto: ✅ / ⚠️ / ❌}
- ✅ Lo bueno: {fortaleza}
- ⚠️ Mejorable: {oportunidad concreta con línea}
- ❌ Bloqueante: {problema grave}
```
