"""LeoStatus — HUD nativo para leo-code con pipeline KC-RAG en vivo.

Auto-adaptativo: 3 modos (minimal, compact, full) según la actividad del agente.
Tema por tipo de tarea (debug=rojo, test_gen=verde, audit=amarillo, etc).
"""

import os
import subprocess
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.table import Table


_TASK_THEMES = {
    "debug": "red", "test_gen": "green", "audit": "yellow",
    "code_query": "blue", "code_gen": "cyan", "refactor": "magenta",
    "review": "bright_blue", "optimize": "bright_yellow",
    "search": "white", "onboard": "bright_cyan", "design_review": "purple",
    "code_edit": "orange1", "no_code": "dim",
}


class LeoStatus:
    """Terminal HUD con pipeline KC-RAG en vivo y tema por tarea."""

    def __init__(self, console: Console, repo_path: str = ".",
                 model: str = "", plugins: list[str] | None = None,
                 skills: list[str] | None = None, session_id: str = ""):
        self.console = console
        self.repo_path = repo_path
        self.model = model
        self.plugins = plugins or []
        self.skills = skills or []
        self.session_id = session_id[:12] if session_id else ""
        self.mode = "minimal"
        self._query = ""
        self._task_type = ""
        self._context_tokens = 0
        self._total_tokens = 0
        self._total_saved = 0
        self._iterations = 0
        self._duration_ms = 0

    @property
    def task_color(self) -> str:
        return _TASK_THEMES.get(self._task_type, "dim")

    @property
    def _git_branch(self) -> str:
        try:
            r = subprocess.run("git branch --show-current", shell=True,
                               cwd=self.repo_path, capture_output=True, text=True, timeout=5)
            return r.stdout.strip() or "?"
        except Exception:
            return "?"

    @property
    def _capsules_count(self) -> str:
        cache_dir = Path(os.getenv("LEO_CACHE_DIR", "./cache"))
        idx_path = cache_dir / "kc_index.json.gz"
        if idx_path.exists():
            try:
                import gzip, json
                data = json.loads(gzip.decompress(idx_path.read_bytes()))
                return str(data.get("total_capsules", "?"))
            except Exception:
                return "?"
        return "?"

    @property
    def _cache_hit_rate(self) -> str:
        try:
            from leo_code.core.metrics import get_metrics
            snap = get_metrics().snapshot()
            total = snap.cache_hits + snap.cache_misses
            return f"{int(snap.cache_hits / max(total, 1) * 100)}%"
        except Exception:
            return "?"

    def start_query(self, query: str, task_type: str = ""):
        self.mode = "full"
        self._query = query[:80]
        if task_type:
            self._task_type = task_type

    def update_context(self, tokens: int, task_type: str = ""):
        self._context_tokens = tokens
        if task_type:
            self._task_type = task_type

    def end_query(self, tokens: int, iterations: int, duration_ms: int, saved: int):
        self.mode = "compact"
        self._total_tokens = tokens
        self._iterations = iterations
        self._duration_ms = duration_ms
        self._total_saved += saved

    def idle(self):
        self.mode = "minimal"
        self._query = ""
        self._task_type = ""
        self._context_tokens = 0

    def render(self) -> str:
        lines = []
        if self.mode == "minimal":
            lines.append(self._line_header())
        elif self.mode == "compact":
            lines.append(self._line_header())
            lines.append(self._line_footer())
        elif self.mode == "full":
            lines.append(self._line_header())
            lines.append(self._line_query())
            lines.append(self._line_pipeline())
        return "\n".join(lines)

    def _line_header(self) -> str:
        parts = []
        if self.model:
            parts.append(f"● {self.model[:30]}")
        branch = self._git_branch
        if branch and branch != "?":
            parts.append(f"▲ {branch}")
        if self.plugins:
            parts.append(f"⚡{len(self.plugins)} plugins")
        if self.skills:
            parts.append(f"🧠{len(self.skills)} skills")
        rate = self._cache_hit_rate
        if rate and rate != "?":
            parts.append(f"🔥{rate} cache")
        return " │ ".join(parts)

    def _line_query(self) -> str:
        q = self._query or "..."
        ttype = self._task_type or ""
        ctx = f" · [{self.task_color}]{ttype}[/{self.task_color}]" if ttype else ""
        tokens = f" · {self._context_tokens} tok" if self._context_tokens else ""
        return f"  > {q}{ctx}{tokens}"

    def _line_pipeline(self) -> str:
        caps = self._capsules_count
        parts = []
        if caps and caps != "?":
            parts.append(f"📦{caps} caps")
        if self._context_tokens:
            parts.append(f"contexto {self._context_tokens}t")
        if self._task_type:
            parts.append(f"[{self.task_color}]{self._task_type}[/{self.task_color}]")
        return f"  KC-RAG: {' │ '.join(parts)}" if parts else ""

    def _line_footer(self) -> str:
        parts = []
        if self._total_saved:
            saved = self._total_saved
            parts.append(f"▲ {saved:,} tok ahorrados ({int(min(saved/20000,1)*100)}% eficiencia)")
        if self._iterations:
            parts.append(f"{self._iterations} iters · {self._duration_ms}ms")
        if self.session_id:
            parts.append(f"💾 {self.session_id}")
        return " │ ".join(parts) if parts else ""
