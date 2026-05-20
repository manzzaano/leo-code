"""Tools: herramientas del agente (read_file, write_file, replace_in_file, list_files, execute_command, run_tests, git_diff, search_code)."""

import subprocess
import sys
from pathlib import Path


class ToolRegistry:
    """Registro de herramientas disponibles para el agente."""

    def __init__(self):
        self._tools = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "replace_in_file": self.replace_in_file,
            "list_files": self.list_files,
            "execute_command": self.execute_command,
            "run_tests": self.run_tests,
            "git_diff": self.git_diff,
            "search_code": self.search_code,
        }

    def get_definitions(self) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": "read_file",
                "description": "Lee el contenido completo de un archivo del repositorio",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string", "description": "Ruta relativa al archivo"}},
                    "required": ["file_path"],
                },
            }},
            {"type": "function", "function": {
                "name": "write_file",
                "description": "Escribe contenido en un archivo (sobrescribe si existe, crea directorios si no existen)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Ruta relativa al archivo a escribir"},
                        "content": {"type": "string", "description": "Contenido completo del archivo"},
                    },
                    "required": ["file_path", "content"],
                },
            }},
            {"type": "function", "function": {
                "name": "replace_in_file",
                "description": "Reemplaza un fragmento exacto de texto en un archivo por otro. Usa old_string para identificar qué cambiar y new_string como reemplazo. Solo reemplaza la primera ocurrencia.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Ruta relativa al archivo"},
                        "old_string": {"type": "string", "description": "Texto exacto a reemplazar (debe ser único en el archivo)"},
                        "new_string": {"type": "string", "description": "Texto de reemplazo"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            }},
            {"type": "function", "function": {
                "name": "list_files",
                "description": "Lista archivos y directorios del repositorio. Usa depth para limitar profundidad y pattern para filtrar (ej. '*.py').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directorio a listar (relativo al repo, '.' por defecto)"},
                        "depth": {"type": "integer", "description": "Profundidad maxima (default 2)"},
                        "pattern": {"type": "string", "description": "Filtro glob (ej. '*.py', '**/*.md')"},
                    },
                },
            }},
            {"type": "function", "function": {
                "name": "execute_command",
                "description": "Ejecuta un comando en la terminal y retorna la salida",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Comando a ejecutar"},
                    },
                    "required": ["command"],
                },
            }},
            {"type": "function", "function": {
                "name": "run_tests",
                "description": "Ejecuta tests del repositorio (pytest). Opcionalmente filtra por archivo, directorio o keyword.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Archivo o directorio de tests (opcional, default: todo el repo)"},
                        "keyword": {"type": "string", "description": "Filtrar tests por keyword (ej. nombre de funcion)"},
                    },
                },
            }},
            {"type": "function", "function": {
                "name": "git_diff",
                "description": "Muestra los cambios (git diff) respecto al estado anterior",
                "parameters": {"type": "object", "properties": {}},
            }},
            {"type": "function", "function": {
                "name": "search_code",
                "description": "Busca un patron de texto en los archivos del repositorio",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Patron a buscar"},
                    },
                    "required": ["pattern"],
                },
            }},
        ]

    def get_openai_definitions(self) -> list[dict]:
        return self.get_definitions()

    def execute(self, name: str, arguments: dict, repo_path: str = ".") -> str:
        tool_fn = self._tools.get(name)
        if tool_fn:
            return tool_fn(arguments, repo_path)
        return f"[Tool '{name}' no encontrada]"

    def read_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            return f"[Error leyendo {path}: {e}]"

    def write_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"[Escrito: {path} ({len(content)} chars)]"
        except Exception as e:
            return f"[Error escribiendo {path}: {e}]"

    def replace_in_file(self, args: dict, repo_path: str) -> str:
        path = Path(repo_path) / args.get("file_path", "")
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if not old:
            return "[Error: old_string vacio]"
        try:
            content = path.read_text(encoding="utf-8")
            count = content.count(old)
            if count == 0:
                return f"[Error: old_string no encontrado en {path}]"
            if count > 1:
                return f"[Error: old_string aparece {count} veces en {path}. Debe ser unico.]"
            content = content.replace(old, new, 1)
            path.write_text(content, encoding="utf-8")
            return f"[Reemplazado en {path}: {len(old)} → {len(new)} chars]"
        except Exception as e:
            return f"[Error en replace_in_file {path}: {e}]"

    def list_files(self, args: dict, repo_path: str) -> str:
        base = Path(repo_path) / args.get("path", ".")
        depth = args.get("depth", 2)
        pattern = args.get("pattern", "")
        try:
            if pattern:
                matches = sorted(base.rglob(pattern))
            else:
                matches = sorted(base.rglob("*"))
            lines = []
            for p in matches:
                if p.is_dir():
                    continue
                rel = p.relative_to(base)
                if len(rel.parts) > depth:
                    continue
                size = p.stat().st_size
                lines.append(f"  {rel} ({size} B)" if size < 1024 else f"  {rel} ({size // 1024} KB)")
            return "\n".join(lines[:80]) if lines else "[Directorio vacio]"
        except Exception as e:
            return f"[Error listando {base}: {e}]"

    def execute_command(self, args: dict, repo_path: str) -> str:
        cmd = args.get("command", "")
        cwd = args.get("cwd", repo_path)
        if sys.platform == "win32":
            cmd = self._translate_windows(cmd)
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd,
                                     capture_output=True, text=True, timeout=60)
            output = (result.stdout + result.stderr).strip()
            return output if output else "[comando ejecutado sin salida]"
        except subprocess.TimeoutExpired:
            return f"[Timeout: {cmd[:100]}...]"
        except Exception as e:
            return f"[Error ejecutando '{cmd[:100]}...': {e}]"

    def run_tests(self, args: dict, repo_path: str) -> str:
        parts = ["pytest"]
        if keyword := args.get("keyword"):
            parts.append(f"-k {keyword}")
        if path := args.get("path"):
            parts.append(path)
        cmd = " ".join(parts)
        cwd = repo_path
        try:
            result = subprocess.run(cmd, shell=True, cwd=cwd,
                                     capture_output=True, text=True, timeout=120)
            output = (result.stdout + result.stderr).strip()
            return output if output else "[pytest sin salida]"
        except subprocess.TimeoutExpired:
            return f"[Timeout: pytest...]"
        except FileNotFoundError:
            return "[Error: pytest no instalado. pip install pytest]"
        except Exception as e:
            return f"[Error pytest: {e}]"

    @staticmethod
    def _translate_windows(cmd: str) -> str:
        c = cmd.strip()
        if c.startswith("mkdir -p "):
            path = c[9:].strip().strip('"')
            return f'New-Item -ItemType Directory -Path "{path}" -Force | Out-Null'
        if c.startswith("mkdir "):
            path = c[6:].strip().strip('"')
            return f'New-Item -ItemType Directory -Path "{path}" -Force | Out-Null'
        if c.startswith("rm -rf ") or c.startswith("rm -r "):
            parts = c.split(" ", 2)
            path = parts[-1].strip().strip('"') if len(parts) > 2 else ""
            return f'Remove-Item -LiteralPath "{path}" -Recurse -Force -ErrorAction SilentlyContinue' if path else c
        if c == "ls" or c.startswith("ls "):
            rest = c[3:] if len(c) > 2 else ""
            return f"Get-ChildItem {rest}".strip()
        if c.startswith("cat "):
            return f"Get-Content {c[4:]}"
        if c.startswith("touch "):
            path = c[6:].strip().strip('"')
            return f'New-Item -ItemType File -Path "{path}" -Force | Out-Null'
        if c.startswith("cp ") or c.startswith("copy "):
            parts = c.split(" ")
            if len(parts) >= 3:
                return f'Copy-Item "{parts[1]}" "{parts[2]}"'
        if c.startswith("mv "):
            parts = c.split(" ")
            if len(parts) >= 3:
                return f'Move-Item "{parts[1]}" "{parts[2]}"'
        if c.endswith("2>nul") or c.endswith("2>/dev/null") or "pytest" in c:
            return c
        return c

    def git_diff(self, args: dict, repo_path: str) -> str:
        try:
            result = subprocess.run("git diff", shell=True, cwd=repo_path,
                                     capture_output=True, text=True, timeout=30)
            return result.stdout or "[Sin cambios]"
        except Exception as e:
            return f"[Error git diff: {e}]"

    def search_code(self, args: dict, repo_path: str) -> str:
        pattern = args.get("pattern", "")
        search_path = Path(repo_path) / args.get("path", ".")
        try:
            result = subprocess.run(
                f'rg --line-number "{pattern}" "{search_path}"',
                shell=True, capture_output=True, text=True, timeout=30
            )
            return result.stdout or "[No encontrado]"
        except Exception:
            matches = []
            for p in search_path.rglob("*.py"):
                try:
                    for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                        if pattern in line:
                            matches.append(f"{p}:{i}: {line.strip()[:120]}")
                except Exception:
                    continue
            return "\n".join(matches[:20]) or "[No encontrado]"
