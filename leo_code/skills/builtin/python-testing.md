---
name: python-testing
description: Generar tests pytest con fixtures, parametrize, y mocking mínimo
version: "1.0"
triggers:
  - "escribe tests?"
  - "genera tests?"
  - "write tests?"
  - "añade tests?"
  - "testear"
  - "pytest"
  - "unit tests?"
task_types:
  - test_gen
file_extensions:
  - py
preferred_model: deepseek/deepseek-v4-pro
tools_required:
  - run_tests
priority: 10
---

# Python Testing

Generas tests pytest profesionales. Sigue estas reglas.

## Reglas

- Usa **pytest fixtures** para setup/teardown en lugar de setUp/tearDown
- Prefiere `@pytest.mark.parametrize` sobre bucles en tests
- Sigue **Arrange-Act-Assert** (AAA) en cada test
- **No mockees lo que no es tuyo**: solo mockea dependencias externas (APIs, DB, filesystem)
- Usa `pytest.raises` para excepciones, no try/except
- Nombres de test descriptivos: `test_<que_hace>_<resultado_esperado>`
- Un test por comportamiento, no un test por método
- Usa `conftest.py` para fixtures compartidos
- Si el proyecto usa pytest-asyncio, usa `@pytest.mark.asyncio`
- Lee los tests existentes en el repo para seguir el estilo local

## Estructura

```python
import pytest

def test_user_creation_success(db_fixture):
    # Arrange
    user_data = {"name": "Alice", "email": "alice@test.com"}
    # Act
    user = UserService.create(user_data)
    # Assert
    assert user.name == "Alice"
    assert user.id is not None

def test_user_creation_missing_email():
    with pytest.raises(ValidationError, match="email is required"):
        UserService.create({"name": "Bob"})
```
