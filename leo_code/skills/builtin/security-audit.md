---
name: security-audit
description: Auditoría de seguridad OWASP top 10, secrets, injection, input validation
version: "1.0"
triggers:
  - "seguridad"
  - "security"
  - "audit"
  - "auditar"
  - "vulnerabilidad"
  - "vulnerability"
  - "sql injection"
  - "xss"
  - "csrf"
  - "secrets?"
  - "token"
  - "contraseña"
  - "password"
task_types:
  - audit
file_extensions:
  - py
  - ts
  - js
  - go
  - java
  - php
  - rb
priority: 9
---

# Security Audit

Auditas código buscando vulnerabilidades de seguridad. Sigue OWASP top 10.

## Checklist OWASP Top 10

### 1. Broken Access Control
- ¿Cada endpoint verifica autenticación/autorización?
- ¿Hay IDOR? (Insecure Direct Object Reference — `GET /users/123` sin verificar que 123 es el usuario actual)
- ¿Los tokens JWT verifican firma y expiración?

### 2. Cryptographic Failures
- ¿Contraseñas hasheadas con bcrypt/scrypt/argon2? (nunca MD5/SHA1)
- ¿Datos sensibles en texto plano en logs o respuestas?
- ¿HTTPS forzado?

### 3. Injection
- **SQL**: ¿Usa parámetros preparados, nunca concatenación de strings?
- **NoSQL**: ¿Input sanitizado antes de queries MongoDB?
- **Command**: ¿`subprocess.run(cmd, shell=True)` con input de usuario? Usa `shell=False` y lista de args
- **LDAP/XML/OS**: Mismo patrón — nunca interpolar input de usuario

### 4. Insecure Design
- ¿Rate limiting en endpoints sensibles? (login, reset password)
- ¿Se puede hacer brute force?
- ¿Hay límites de tamaño en uploads?

### 5. Security Misconfiguration
- ¿Headers de seguridad? (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- ¿DEBUG=True en producción?
- ¿Puertos/endpoints expuestos innecesariamente?
- ¿Errores muestran stack traces al usuario?

### 6. Secrets y Credenciales
- Busca: `sk-`, `ghp_`, `Bearer`, `password = "`, `secret = "`, `token = "`
- ¿API keys en el código fuente? Deben ir en env vars
- ¿`.env` en `.gitignore`?
- ¿AWS keys, database passwords, JWT secrets hardcodeados?

### 7. Input Validation
- ¿Input validado en el servidor, no solo en el cliente?
- ¿File uploads validan tipo MIME y tamaño?
- ¿XML/JSON parsing con límites? (billion laughs attack, JSON bomb)

### Formato de respuesta

```
🔴 CRÍTICO: {vulnerabilidad} — {archivo}:{línea} — {recomendación}
🟡 MEDIO: {hallazgo} — {archivo}:{línea} — {recomendación}
🟢 OK: {práctica correcta encontrada}
```
