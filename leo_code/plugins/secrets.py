"""Secrets Plugin — bloquea commits que contengan API keys, passwords o tokens."""

import re
from leo_code.plugins import Plugin, register_builtin

_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey|secret|token|password|passwd)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}', "possible secret (API key, token, password)"),
    (r'(?i)-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PRIVATE)\s+KEY-----', "private key block"),
    (r'(?i)ghp_[A-Za-z0-9_]{36,}', "GitHub PAT"),
    (r'(?i)sk-[A-Za-z0-9_]{32,}', "OpenAI API key"),
    (r'(?i)gho_[A-Za-z0-9_]{36,}', "GitHub OAuth token"),
]

class SecretsPlugin(Plugin):
    name = "secrets"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        extra = config.get("extra_patterns", [])
        for p in extra:
            _PATTERNS.append((re.compile(p["regex"]), p.get("description", "custom pattern")))

    def on_pre_tool(self, tool_name: str, args: dict) -> bool:
        if tool_name not in ("write", "edit", "bash", "read"):
            return True
        text = ""
        if tool_name == "write":
            text = args.get("content", "")
        elif tool_name == "edit":
            text = args.get("newString", "")
        elif tool_name == "bash":
            text = args.get("command", "")
            if "commit" not in text and "push" not in text:
                return True
        elif tool_name == "read":
            return True
        findings = []
        for pattern, desc in _PATTERNS:
            for m in re.finditer(pattern, text):
                findings.append(f"  - Línea ~{text[:m.start()].count(chr(10)) + 1}: {desc} (coincidencia: {m.group()[:20]}...)")
                break
        if findings:
            summary = "\n".join(findings)
            raise PermissionError(
                f"[plugin:secrets] Bloqueado — se detectaron secrets en '{tool_name}':\n{summary}\n\n"
                f"Elimínalos o añádelos a .gitignore/.env.example antes de continuar."
            )
        return True

register_builtin("secrets", SecretsPlugin)
