import ast
import os
import sys

def has_docstring(node):
    if (node.body and 
        isinstance(node.body[0], ast.Expr) and 
        isinstance(node.body[0].value, (ast.Constant, ast.Str))):
        doc = node.body[0].value.value if isinstance(node.body[0].value, ast.Constant) else node.body[0].value.s
        if isinstance(doc, str) and doc.strip():
            return True
    return False

def count_loc(filepath, start_line, end_line):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    count = 0
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i].strip()
        if line and not line.startswith('#'):
            count += 1
    return count

results = []
root_dir = '.'
exclude_dirs = {'__pycache__', '.git', 'venv', '.venv', 'node_modules', '.pytest_cache', '.mypy_cache', '.ruff_cache'}

for dirpath, dirnames, filenames in os.walk(root_dir):
    dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith('.')]
    for fname in filenames:
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(dirpath, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
        except Exception as e:
            sys.stderr.write(f"Error parsing {fpath}: {e}\n")
            continue
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not has_docstring(node):
                    name = node.name
                    kind = 'Class' if isinstance(node, ast.ClassDef) else 'Function'
                    loc = count_loc(fpath, node.lineno, node.end_lineno)
                    results.append((loc, fpath, node.lineno, kind, name))

results.sort(key=lambda x: -x[0])

print(f"Total: {len(results)} funciones/clases sin docstring")
print()
print("Top 10:")
print(f"{'LOC':<6} {'Tipo':<10} {'Nombre':<50} {'Archivo':<60} {'Linea':<6}")
print("-" * 130)
for loc, fpath, lineno, kind, name in results[:10]:
    relpath = os.path.relpath(fpath, root_dir)
    print(f"{loc:<6} {kind:<10} {name:<50} {relpath:<60} {lineno:<6}")

print()
print("--- Todas con >= 10 LOC ---")
for loc, fpath, lineno, kind, name in results:
    if loc >= 10:
        relpath = os.path.relpath(fpath, root_dir)
        print(f"{loc:<6} {kind:<10} {name:<50} {relpath:<60} {lineno:<6}")
