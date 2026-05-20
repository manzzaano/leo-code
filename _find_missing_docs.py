import ast, os, sys

def main():
    count = 0
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', '.venv', 'venv')]
        for f in files:
            if not f.endswith('.py'):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, 'r', encoding='utf-8') as fh:
                    tree = ast.parse(fh.read(), filename=fp)
            except SyntaxError as e:
                print(f"SyntaxError en {fp}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"Error en {fp}: {e}", file=sys.stderr)
                continue
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not ast.get_docstring(node):
                        count += 1
                        if count <= 20:
                            print(f"FUNCION  {node.name:30s}  {fp:50s}  L{node.lineno}")
                elif isinstance(node, ast.ClassDef):
                    if not ast.get_docstring(node):
                        count += 1
                        if count <= 20:
                            print(f"CLASE    {node.name:30s}  {fp:50s}  L{node.lineno}")
    
    print(f"\nTotal elementos sin docstring: {count}")

if __name__ == '__main__':
    main()
