#!/usr/bin/env python3
"""Analiza funciones/clases sin docstring en leo-code, ordenadas por lineas."""

import ast
import os
from pathlib import Path

BASE = Path(r"C:\Users\Ismael\Desktop\leo-code\leo_code")

def get_end_lineno(node):
    """Obtiene la linea final real de un nodo, manejando nodos sin end_lineno."""
    return getattr(node, 'end_lineno', node.lineno) or node.lineno

def has_docstring(node):
    """Verifica si un nodo (funcion/clase/modulo) tiene docstring."""
    body = getattr(node, 'body', [])
    if not body:
        return False
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, (ast.Str, ast.Constant)):
        val = first.value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return True
        if isinstance(val, ast.Str):
            return True
    return False

def iter_functions_classes(tree, filename):
    """Itera sobre todas las funciones y clases definidas en un arbol AST."""
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            lineno = node.lineno
            end_lineno = get_end_lineno(node)
            lines = end_lineno - lineno + 1
            has_doc = has_docstring(node)
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            if not has_doc:
                results.append((lines, name, filename, lineno, kind))
    return results

def main():
    all_items = []
    for root, dirs, files in os.walk(BASE):
        # Saltar __pycache__
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith('.py'):
                fpath = Path(root) / f
                relpath = fpath.relative_to(BASE.parent)  # relativo a leo-code/
                try:
                    source = fpath.read_text(encoding='utf-8')
                    tree = ast.parse(source, filename=str(fpath))
                    items = iter_functions_classes(tree, str(relpath))
                    all_items.extend(items)
                except SyntaxError:
                    pass  # ignorar archivos con errores de sintaxis

    # Ordenar por lineas descendente
    all_items.sort(key=lambda x: x[0], reverse=True)

    print(f"{'Lineas':>6} {'Tipo':<10} {'Nombre':<50} {'Archivo':<60} Linea")
    print("=" * 150)
    for lines, name, fpath, lineno, kind in all_items[:10]:
        print(f"{lines:>6} {kind:<10} {name:<50} {fpath:<60} {lineno}")

    print(f"\n--- Total de funciones/clases SIN docstring: {len(all_items)} ---")

if __name__ == "__main__":
    main()
