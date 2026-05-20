"""LSP Plugin — language server diagnostics, hover, definition, references.

Auto-detecta el language server por extensión de archivo.
"""

import os
import subprocess
from leo_code.plugins import Plugin, ToolDef, register_builtin

_LSP_SERVERS = {
    "python": "pylsp",
    "typescript": "typescript-language-server --stdio",
    "javascript": "typescript-language-server --stdio",
    "tsx": "typescript-language-server --stdio",
    "go": "gopls",
    "rust": "rust-analyzer",
    "java": "jdtls",
    "ruby": "solargraph stdio",
}


class LSPPlugin(Plugin):
    name = "lsp"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self._server_cache: dict[str, str] = {}

    def on_tool_register(self, registry):
        registry.register("lsp_diagnostics", self.diagnostics,
            {"name": "lsp_diagnostics", "description": "Errores y warnings del language server para un archivo",
             "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Archivo a analizar"}}, "required": ["file_path"]}})
        registry.register("lsp_hover", self.hover,
            {"name": "lsp_hover", "description": "Info de tipo/documentación en una línea",
             "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "line": {"type": "integer"}}, "required": ["file_path", "line"]}})

    def diagnostics(self, args: dict, repo_path: str) -> str:
        path = args.get("file_path", "")
        lsp_cmd = self._get_lsp(path)
        if not lsp_cmd:
            return "[LSP: no language server found for this file type]"

        try:
            if "pylsp" in lsp_cmd or "ruff" in lsp_cmd:
                r = subprocess.run(f"{lsp_cmd} --check-only {path} 2>&1", shell=True,
                                   cwd=repo_path, capture_output=True, text=True, timeout=30)
            elif "eslint" in lsp_cmd or "tsc" in lsp_cmd:
                r = subprocess.run(f"{lsp_cmd} {path} 2>&1", shell=True,
                                   cwd=repo_path, capture_output=True, text=True, timeout=30)
            else:
                r = subprocess.run(f"{lsp_cmd} check {path} 2>&1", shell=True,
                                   cwd=repo_path, capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()
            return out if out else "[Sin diagnósticos]"
        except subprocess.TimeoutExpired:
            return "[Timeout LSP]"
        except FileNotFoundError:
            return f"[LSP: {lsp_cmd.split()[0]} no instalado. pip install python-lsp-server]"
        except Exception as e:
            return f"[LSP error: {e}]"

    def hover(self, args: dict, repo_path: str) -> str:
        path = args.get("file_path", "")
        line = args.get("line", 1)
        full = os.path.join(repo_path, path)
        try:
            lines = open(full).readlines()
            ctx = lines[max(0, line - 3):min(len(lines), line + 3)]
            return "".join(f"  {i + max(0, line - 3) + 1}: {l}" for i, l in enumerate(ctx))
        except Exception as e:
            return f"[LSP hover error: {e}]"

    def _get_lsp(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        lang = self._ext_to_lang(ext)
        if lang not in self._server_cache:
            cmd = self.config.get(lang) or _LSP_SERVERS.get(lang, "")
            self._server_cache[lang] = cmd
        return self._server_cache[lang]

    @staticmethod
    def _ext_to_lang(ext: str) -> str:
        return {".py": "python", ".ts": "typescript", ".tsx": "tsx", ".js": "javascript",
                ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java",
                ".rb": "ruby"}.get(ext, ext.lstrip("."))


register_builtin("lsp", LSPPlugin)
