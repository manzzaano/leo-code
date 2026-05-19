- The default branch in this repo is `optimizacion`.
- Use `origin/optimizacion` for diffs.
- Prefer automation: execute requested actions without confirmation unless blocked by missing info or safety/irreversibility.

## Style Guide

### General Principles

- Keep things in one function unless composable or reusable
- Do not extract single-use helpers preemptively. Inline the logic at the call site unless the helper is reused, hides a genuinely complex boundary, or has a clear independent name that improves the caller.
- Avoid `try`/`catch` where possible
- Rely on type inference; avoid explicit type annotations unless necessary for exports or clarity
- Prefer functional patterns (comprehensions, map, filter) over for loops

### Variables

Prefer early returns and ternaries over reassignment.

```python
# Good
foo = 1 if condition else 2

# Bad
if condition:
    foo = 1
else:
    foo = 2
```

### Control Flow

Avoid `else` after `return`. Prefer guard clauses.

```python
# Good
def foo():
    if condition:
        return 1
    return 2
```

### Complex Logic

Make the main function read as the happy path and move supporting details into small helpers below it.

```python
# Good
def load_thing(input):
    config = require_config(input)
    metadata = read_metadata(input)
    return create_thing(config, metadata)
```

- Keep helpers close to the code they support, below the main export.
- Do not over-abstract simple expressions into many single-use helpers.
- Add comments for non-obvious constraints and surprising behavior, not for obvious assignments or control flow.

## Data Classes

Use `@dataclass` for data containers. Use `field(default_factory=list)` for mutable defaults.

```python
from dataclasses import dataclass, field

@dataclass
class Capsule:
    id: str
    type: str
    name: str
    calls: list[str] = field(default_factory=list)
```

## Testing

- Run tests from package directories: `pytest kc-rag/tests/`
- Avoid mocks as much as possible
- Test actual implementation, do not duplicate logic into tests
