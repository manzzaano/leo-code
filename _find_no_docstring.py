import ast
import os

def get_function_class_info(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content, filename=filepath)
    except (SyntaxError, UnicodeDecodeError) as e:
        return []
    
    results = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            lineno = node.lineno
            end_lineno = node.end_lineno if hasattr(node, 'end_lineno') else lineno
            lines_of_code = end_lineno - lineno + 1
            
            has_docstring = False
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant)):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    has_docstring = True
                elif isinstance(val, ast.Str):
                    has_docstring = True
            
            if not has_docstring:
                results.append((filepath, lineno, name, 'function', lines_of_code))
        
        if isinstance(node, ast.ClassDef):
            name = node.name
            lineno = node.lineno
            end_lineno = node.end_lineno if hasattr(node, 'end_lineno') else lineno
            lines_of_code = end_lineno - lineno + 1
            
            has_docstring = False
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant)):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    has_docstring = True
                elif isinstance(val, ast.Str):
                    has_docstring = True
            
            if not has_docstring:
                results.append((filepath, lineno, name, 'class', lines_of_code))
    
    return results

# Buscar recursivamente
all_results = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'venv', 'env', '.venv', 'node_modules', '.pytest_cache', '.mypy_cache')]
    for f in files:
        if f.endswith('.py'):
            filepath = os.path.join(root, f)
            all_results.extend(get_function_class_info(filepath))

all_results.sort(key=lambda x: x[4], reverse=True)

print(f'Total de funciones/clases sin docstring: {len(all_results)}')
print()
print('TOP 10 - Funciones/Clases sin docstring (ordenadas por líneas de código):')
print('=' * 110)
print(f'{"#":<4} {"Archivo":<50} {"Línea":<6} {"Tipo":<10} {"Nombre":<30} {"LOC":<6}')
print('=' * 110)
for i, (filepath, lineno, name, typ, loc) in enumerate(all_results[:10], 1):
    short_path = filepath.replace('\\', '/').replace('./', '')
    print(f'{i:<4} {short_path:<50} {lineno:<6} {typ:<10} {name:<30} {loc:<6}')
print('=' * 110)
