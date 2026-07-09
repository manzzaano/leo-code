"""SecretGuard — intercepta write/edit/git_commit y escanea por secrets antes de permitirlos."""

import re
from pathlib import Path
from leo_code.plugins import Plugin, register_builtin

_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|credential|auth_token)\s*[:=]\s*["\']?[A-Za-z0-9_\-@#$%^&+=]{16,}', "possible secret (key, token, password)"),
    (r'(?i)-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PRIVATE)\s+KEY-----', "private key block"),
    (r'(?i)gh[pousr]_[A-Za-z0-9_]{36,}', "GitHub token (PAT, OAuth, etc)"),
    (r'(?i)sk-[A-Za-z0-9_]{32,}', "OpenAI API key"),
    (r'(?i)xox[abpors]-[A-Za-z0-9_\-]{10,}', "Slack token"),
    (r'(?i)AKIA[0-9A-Z]{16}', "AWS access key"),
    (r'(?i)-----BEGIN\s+CERTIFICATE-----', "certificate block — ¿seguro que debe ir en el repo?"),
]

class SecretGuardPlugin(Plugin):
    name = "secretguard"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self.allowlist_paths = [Path(repo_path) / p for p in config.get("allowlist_paths", [])]

    def on_pre_tool(self, tool_name: str, args: dict) -> bool:
        if tool_name not in ("write", "edit", "bash"):
            return True

        text = ""
        filepath = ""

        if tool_name == "write":
            text = args.get("content", "")
            filepath = args.get("filePath", "")
        elif tool_name == "edit":
            text = args.get("newString", "")
            filepath = args.get("filePath", "")
        elif tool_name == "bash":
            text = args.get("command", "")
            if "commit" not in text and "push" not in text:
                return True

        if self._is_allowlisted(filepath):
            return True

        findings = self._scan(text)
        if findings:
            summary = "\n".join(findings)
            raise PermissionError(
                f"[plugin:secretguard] Bloqueado — secrets detectados en '{tool_name}' "
                f"({'archivo: ' + filepath if filepath else 'comando: ' + text[:60] + '...'}):\n"
                f"{summary}\n\n"
                f"Acciones recomendadas:\n"
                f"  - Usa variables de entorno en lugar de valores hardcodeados\n"
                f"  - Añade el archivo a allowlist_paths en la config si es un falso positivo\n"
                f"  - Para tests, usa valores placeholder como 'sk-test-...'"
            )
        return True

    def _is_allowlisted(self, filepath: str) -> bool:
        if not filepath:
            return False
        p = Path(filepath)
        for allowed in self.allowlist_paths:
            try:
                p.relative_to(allowed)
                return True
            except ValueError:
                continue
        return False

    def _scan(self, text: str) -> list[str]:
        findings = []
        for pattern, desc in _PATTERNS:
            matches = list(re.finditer(pattern, text))
            if matches:
                for m in matches[:3]:
                    line_no = text[:m.start()].count("\n") + 1
                    snippet = m.group()[:30]
                    findings.append(f"  - Línea {line_no}: {desc} (`{snippet}...`)")
                if len(matches) > 3:
                    findings.append(f"  - ... y {len(matches) - 3} coincidencias más de '{desc}'")
        return findings


register_builtin("secretguard", SecretGuardPlugin)
