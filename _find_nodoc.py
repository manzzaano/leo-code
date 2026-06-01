import ast, os, sys

def has_docstring(node):
    if not node.body:
        return False
    first = node.body[0]
    return isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant, ast.Str))

results = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', '.venv', 'venv')]
    for f in files:
        if f.endswith('.py'):
            fp = os.path.join(root, f)
            try:
                with open(fp, encoding='utf-8') as fh:
                    src = fh.read()
                tree = ast.parse(src, filename=fp)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if not has_docstring(node):
                            nlines = node.end_lineno - node.lineno + 1
                            kind = 'Class' if isinstance(node, ast.ClassDef) else 'Func'
                            results.append((nlines, node.name, fp, node.lineno, kind))
            except Exception as e:
                print(f'Error en {fp}: {e}', file=sys.stderr)

results.sort(key=lambda x: x[0], reverse=True)
print(f'Total: {len(results)}')
print()
for n, name, fp, lineno, kind in results[:10]:
    print(f'{n:>4} lines | {kind:<6} | {name:<40} | {os.path.relpath(fp):<45} | line {lineno}')
