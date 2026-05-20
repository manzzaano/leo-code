"""Linter Plugin — ejecuta linters configurados por lenguaje."""

import subprocess
from leo_code.plugins import Plugin, register_builtin

_DEFAULT_LINTERS = {
    "python": "ruff check --output-format concise 2>&1",
    "javascript": "eslint --format compact . 2>&1",
    "typescript": "eslint --format compact . 2>&1",
    "go": "go vet ./... 2>&1",
    "rust": "cargo clippy --message-format short 2>&1",
}


class LinterPlugin(Plugin):
    name = "linter"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path

    def on_tool_register(self, registry):
        registry.register("run_linter", self.run_linter,
            {"name": "run_linter", "description": "Ejecuta el linter configurado para el lenguaje del proyecto",
             "parameters": {"type": "object", "properties": {
                 "language": {"type": "string", "description": "Lenguaje (python, javascript, go, rust). Auto-detecta si no se especifica."},
             }}})
        registry.register("lint_on_file", self.lint_on_file,
            {"name": "lint_on_file", "description": "Ejecuta linter en un archivo específico",
             "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}})

    def run_linter(self, args: dict, repo_path: str) -> str:
        lang = args.get("language") or self._detect_lang(repo_path)
        cmd = self.config.get(lang) or _DEFAULT_LINTERS.get(lang, "")
        if not cmd:
            return f"[Linter: no configurado para {lang}]"
        try:
            r = subprocess.run(cmd, shell=True, cwd=repo_path, capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()
            return out if out else "[Sin errores de linter]"
        except Exception as e:
            return f"[Linter error: {e}]"

    def lint_on_file(self, args: dict, repo_path: str) -> str:
        path = args.get("file_path", "")
        ext = path.rsplit(".", 1)[-1] if "." in path else ""
        lang = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
                ".go": "go", ".rs": "rust"}.get(f".{ext}", ext)
        cmd = self.config.get(lang) or _DEFAULT_LINTERS.get(lang, "")

        if "ruff" in cmd:
            cmd = f"ruff check {path} --output-format concise 2>&1"
        elif "eslint" in cmd:
            cmd = f"eslint {path} --format compact 2>&1"
        elif "clippy" in cmd:
            cmd = f"cargo clippy --message-format short 2>&1"

        try:
            r = subprocess.run(cmd, shell=True, cwd=repo_path, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr).strip() or "[Sin errores]"
        except Exception as e:
            return f"[Linter error: {e}]"

    def _detect_lang(self, repo_path: str) -> str:
        import os
        files = os.listdir(repo_path) if os.path.isdir(repo_path) else []
        for f in files:
            if "pyproject.toml" in f or "setup.py" in f:
                return "python"
            if "package.json" in f:
                return "typescript"
            if "go.mod" in f:
                return "go"
            if "Cargo.toml" in f:
                return "rust"
        return "python"


register_builtin("linter", LinterPlugin)
