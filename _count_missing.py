import ast, os

funcs = 0
classes = 0
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', '.venv', 'venv')]
    for f in files:
        if not f.endswith('.py') or f.startswith('_'):
            continue
        fp = os.path.join(root, f)
        try:
            with open(fp, 'r', encoding='utf-8') as fh:
                tree = ast.parse(fh.read(), filename=fp)
        except:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not ast.get_docstring(node):
                    funcs += 1
            elif isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    classes += 1

print(f"Funciones sin docstring: {funcs}")
print(f"Clases sin docstring: {classes}")
print(f"Total: {funcs + classes}")
