"""Tools: herramientas del agente (read_file, write_file, execute, git_diff)."""

import subprocess
import sys
from pathlib import Path


class ToolRegistry:
    """Registro de herramientas disponibles para el agente."""

    def __init__(self):
        self._tools = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "execute_command": self.execute_command,
            "git_diff": self.git_diff,
            "search_code": self.search_code,
        }

    def get_definitions(self) -> list[dict]:
        """Retorna definiciones de tools en formato OpenAI/Anthropic."""
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
        """Alias para get_definitions (compatibilidad)."""
        return self.get_definitions()

    def execute(self, name: str, arguments: dict, repo_path: str = ".") -> str:
        """Ejecuta una tool por nombre con sus argumentos."""
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

    @staticmethod
    def _translate_windows(cmd: str) -> str:
        """Traduce comandos Unix comunes a PowerShell/Windows."""
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
        if c.endswith("2>nul") or c.endswith("2>/dev/null"):
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
            # Fallback a grep básico si rg no está instalado
            matches = []
            for p in search_path.rglob("*.py"):
                try:
                    for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                        if pattern in line:
                            matches.append(f"{p}:{i}: {line.strip()[:120]}")
                except Exception:
                    continue
            return "\n".join(matches[:20]) or "[No encontrado]"
