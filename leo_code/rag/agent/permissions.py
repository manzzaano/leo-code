"""PermissionManager — control de ejecución de tools con contexto KC-RAG.

Modos: auto (permitir todo), ask (preguntar con contexto), deny (rechazar todo).
Configurable en leo-code.json:
{
  "permissions": {
    "mode": "ask",
    "auto_allow": ["read_file", "list_files", "search_code", "git_diff"],
    "auto_deny": [],
    "directory_scoped": true
  }
}
"""

import json
import os
from pathlib import Path


class PermissionManager:
    MODES = ("auto", "ask", "deny")

    def __init__(self, config_path: str = "", repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)
        self.config = self._load_config(config_path)
        self.mode = self.config.get("permissions", {}).get("mode", "auto")
        self.auto_allow = set(self.config.get("permissions", {}).get("auto_allow", []))
        self.auto_deny = set(self.config.get("permissions", {}).get("auto_deny", []))
        self.directory_scoped = self.config.get("permissions", {}).get("directory_scoped", False)
        self._session_allow: set[str] = set()  # tools allowed this session
        self._session_deny: set[str] = set()

    def _load_config(self, config_path: str) -> dict:
        paths = [config_path, "leo-code.json", os.path.expanduser("~/.leo-code/config.json")]
        for p in paths:
            if p and Path(p).exists():
                try:
                    return json.loads(Path(p).read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    def check(self, tool_name: str, args: dict, context_hint: str = "") -> tuple[bool, str]:
        """Retorna (allowed, reason)."""
        if self.mode == "deny":
            return False, "deny mode — ejecucion deshabilitada"
        if self.mode == "auto":
            return True, "auto"

        if tool_name in self.auto_allow or tool_name in self._session_allow:
            return True, "auto-allow"
        if tool_name in self.auto_deny or tool_name in self._session_deny:
            return False, "auto-deny"

        # Directory scoping
        if self.directory_scoped:
            file_path = args.get("file_path", "")
            if file_path and not os.path.abspath(os.path.join(self.repo_path, file_path)).startswith(self.repo_path):
                return False, f"fuera del directorio del proyecto: {file_path}"

        # "ask" mode — pedir confirmación
        return True, "ask"  # el CLI maneja la pregunta

    def allow_this_session(self, tool_name: str):
        self._session_allow.add(tool_name)

    def deny_this_session(self, tool_name: str):
        self._session_deny.add(tool_name)

    def context_for_tool(self, tool_name: str, args: dict) -> str:
        """Genera contexto KC-RAG para mostrar POR QUÉ se quiere ejecutar la tool."""
        hints = []
        if tool_name == "replace_in_file":
            hints.append(f"Quiere modificar {args.get('file_path', '?')}")
        elif tool_name == "write_file":
            hints.append(f"Quiere escribir {args.get('file_path', '?')} ({len(args.get('content', ''))} chars)")
        elif tool_name == "execute_command":
            cmd = args.get("command", "")[:100]
            hints.append(f"Quiere ejecutar: {cmd}")
        elif tool_name == "gh_pr_create":
            hints.append(f"Quiere crear PR: {args.get('title', '?')}")
        elif tool_name == "install_deps":
            hints.append(f"Quiere instalar: {args.get('package', 'todas las dependencias')}")
        return " | ".join(hints) or tool_name
