import ast
import os
import sys

def get_all_py_files(root_dir):
    py_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.endswith('.py') and f != '__init__.py':
                fullpath = os.path.join(dirpath, f)
                # skip tests and benchmark dirs
                if '/tests/' in fullpath or '\\tests\\' in fullpath:
                    continue
                if '/benchmark/' in fullpath or '\\benchmark\\' in fullpath:
                    continue
                # skip .git
                if '/.git/' in fullpath or '\\.git\\' in fullpath:
                    continue
                py_files.append(fullpath)
    return py_files

def count_lines_of_code(node):
    """Count lines of code for a function/class (excluding blank lines)."""
    if hasattr(node, 'end_lineno') and node.lineno:
        return node.end_lineno - node.lineno + 1
    return 0

def has_docstring(node):
    """Check if a function/class has a docstring."""
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant)):
        if isinstance(node.body[0].value, ast.Constant):
            return isinstance(node.body[0].value.value, str) and len(node.body[0].value.value.strip()) > 0
        return True
    return False

def analyze_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return []
    
    items = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            # Skip dunder methods except __init__
            if isinstance(node, ast.FunctionDef) and name.startswith('__') and name != '__init__':
                continue
            # Skip private methods starting with _
            if isinstance(node, ast.FunctionDef) and name.startswith('_') and not name.startswith('__') and name != '__init__':
                continue
            
            loc = count_lines_of_code(node)
            
            if not has_docstring(node):
                items.append({
                    'name': name,
                    'type': 'class' if isinstance(node, ast.ClassDef) else 'function',
                    'file': filepath,
                    'line': node.lineno,
                    'loc': loc,
                    # Get the class name if it's a method
                })
    
    return items

def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    files = get_all_py_files(root_dir)
    
    all_items = []
    for f in files:
        relpath = os.path.relpath(f, root_dir)
        items = analyze_file(f)
        for item in items:
            item['file'] = relpath
            all_items.append(item)
    
    # Sort by LOC descending
    all_items.sort(key=lambda x: x['loc'], reverse=True)
    
    print(f"Total functions/classes without docstring: {len(all_items)}")
    print()
    print(f"{'#':<4} {'Name':<35} {'Type':<10} {'LOC':<6} {'File':<50} {'Line':<6}")
    print("-" * 140)
    
    for i, item in enumerate(all_items[:10], 1):
        print(f"{i:<4} {item['name']:<35} {item['type']:<10} {item['loc']:<6} {item['file']:<50} {item['line']:<6}")

    print()
    print("=" * 60)
    print("TOP 10 - Sorted by lines of code (descending)")
    print("=" * 60)

if __name__ == '__main__':
    main()
