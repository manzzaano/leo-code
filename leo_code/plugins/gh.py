"""GitHub CLI Plugin — PRs, issues, repo info vía gh CLI."""

import subprocess
from leo_code.plugins import Plugin, ToolDef, register_builtin


class GitHubPlugin(Plugin):
    name = "gh"
    version = "0.1.0"

    def on_init(self, config: dict, repo_path: str):
        self.config = config
        self.repo_path = repo_path
        self._has_gh = self._check_gh()

    def on_tool_register(self, registry):
        registry.register("gh_pr_create", self.pr_create,
            {"name": "gh_pr_create", "description": "Crear un Pull Request en GitHub",
             "parameters": {"type": "object", "properties": {
                 "title": {"type": "string", "description": "Título del PR"},
                 "body": {"type": "string", "description": "Descripción del PR"},
                 "base": {"type": "string", "description": "Branch base (default: main)"},
             }, "required": ["title"]}})
        registry.register("gh_pr_list", self.pr_list,
            {"name": "gh_pr_list", "description": "Listar Pull Requests abiertos",
             "parameters": {"type": "object", "properties": {}}})
        registry.register("gh_issue_read", self.issue_read,
            {"name": "gh_issue_read", "description": "Leer un issue de GitHub por número",
             "parameters": {"type": "object", "properties": {"number": {"type": "integer", "description": "Número de issue"}}, "required": ["number"]}})
        registry.register("gh_issue_create", self.issue_create,
            {"name": "gh_issue_create", "description": "Crear un issue en GitHub",
             "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title"]}})
        registry.register("gh_repo_info", self.repo_info,
            {"name": "gh_repo_info", "description": "Información del repositorio GitHub (remotes, default branch)",
             "parameters": {"type": "object", "properties": {}}})

    def pr_create(self, args: dict, repo_path: str) -> str:
        title = args.get("title", "")
        body = args.get("body", "")
        base = args.get("base", "main")
        cmd = f"gh pr create --title \"{title}\" --body \"{body}\" --base {base}"
        return self._run(cmd, repo_path)

    def pr_list(self, args: dict, repo_path: str) -> str:
        return self._run("gh pr list --limit 10", repo_path)

    def issue_read(self, args: dict, repo_path: str) -> str:
        number = args.get("number", 0)
        return self._run(f"gh issue view {number}", repo_path)

    def issue_create(self, args: dict, repo_path: str) -> str:
        title = args.get("title", "")
        body = args.get("body", "")
        return self._run(f"gh issue create --title \"{title}\" --body \"{body}\"", repo_path)

    def repo_info(self, args: dict, repo_path: str) -> str:
        remote = self._run("git remote -v", repo_path)
        branch = self._run("git branch -a", repo_path)
        return f"Remotes:\n{remote}\nBranches:\n{branch}"

    def _check_gh(self) -> bool:
        try:
            r = subprocess.run("gh --version", shell=True, capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def _run(self, cmd: str, cwd: str) -> str:
        if "gh " in cmd and not self._has_gh:
            return "[gh CLI no instalado. https://cli.github.com]"
        try:
            r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr).strip() or "[sin salida]"
        except Exception as e:
            return f"[gh error: {e}]"


register_builtin("gh", GitHubPlugin)
