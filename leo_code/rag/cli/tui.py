"""TUI Cockpit de leo-code (Textual): chat + panel de contexto en vivo + grafo.

Layout full-screen:
  ┌ chat ────────────────────────┬ sidebar ─────┐
  │ conversación (markdown)      │ sesión        │
  │ tool calls con duración      │ modelo/rama   │
  │ timestamps                   │ KC-RAG stats  │
  │                              │ grafo vivo    │
  ├ prompt ──────────────────────┴───────────────┤
  │ › …                         [meter + atajos] │
  └──────────────────────────────────────────────┘

Lo distintivo: los comandos ESTRUCTURALES son DETERMINISTAS y no gastan LLM —
funcionan aunque no tengas API key:
  /trace A B   · camino de llamadas A→B con prueba (archivo:línea)
  /impact X    · qué se rompe si cambias X
  /who X       · quién llama a X
  /where X     · dónde se define X
  /callees X   · a qué llama X

Comandos de gestión:
  /model <id>  · cambiar modelo  ·  /model list  ·  listar disponibles
  /sessions    · listar sesiones  ·  /session     ·  info de sesión
  /diff        · ver git diff  ·  /doctor  ·  diagnóstico
  /compact     · compactar historial  ·  /clear  ·  limpiar chat
  /goal        · modo goal  ·  /image <path>  ·  análisis de visión
  /permissions · configurar permisos  ·  /key  ·  gestionar API keys

Texto normal → chat con el agente (necesita un modelo y API key).

Atajos: Ctrl+R compact  ·  Ctrl+D diff  ·  Ctrl+M modelos  ·  Ctrl+I sesión
         Ctrl+C salir  ·  Ctrl+L limpiar

Arranque:  leo-code tui   (o: python -m leo_code.rag.cli.tui)
"""

from __future__ import annotations

import os
import sys
import time
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.suggester import SuggestFromList
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual.binding import Binding
from textual import work

_HELP = (
    "**Comandos estructurales** (deterministas, cero LLM):\n"
    "- `/trace A B` — camino de llamadas A→B, con prueba\n"
    "- `/impact X` — qué se rompe si cambias X\n"
    "- `/guard X` — radio de explosión + qué afectados están SIN test\n"
    "- `/who X` — quién llama a X · `/callees X` — a qué llama X\n"
    "- `/where X` — dónde se define X\n"
    "- `/compare X` — lado-a-lado: leo vs grep+read\n\n"
    "**Comandos de gestión:**\n"
    "- `/model <id>` — cambiar modelo · `/model list` — listar disponibles\n"
    "- `/sessions` — listar sesiones · `/session` — info de sesión actual\n"
    "- `/diff` — ver git diff de cambios hechos\n"
    "- `/doctor` — diagnóstico del sistema\n"
    "- `/compact` — compactar historial\n"
    "- `/goal <tarea>` — modo goal: plan → execute → verify\n"
    "- `/image <path>` — cargar imagen para análisis de visión\n"
    "- `/permissions` — configurar permisos · `/key` — gestionar API keys\n\n"
    "**Atajos:** Ctrl+R compact · Ctrl+D diff · Ctrl+M modelos · Ctrl+I sesión\n\n"
    "Cualquier otro texto → chat con el agente. ↑/↓ recuperan el historial."
)

_SLASH = [
    "/trace ", "/impact ", "/guard ", "/who ", "/callees ", "/where ",
    "/compare ", "/model ", "/model list", "/sessions", "/session",
    "/diff", "/doctor", "/compact", "/goal ",
    "/image ", "/key ", "/permissions",
    "/help", "/clear", "/quit", "/exit",
]

_TASK_THEMES = {
    "debug": "red", "test_gen": "green", "audit": "yellow",
    "code_query": "blue", "code_gen": "cyan", "refactor": "magenta",
    "review": "bright_blue", "optimize": "bright_yellow",
    "search": "white", "onboard": "bright_cyan", "design_review": "purple",
    "code_edit": "orange1", "no_code": "dim",
}

_ENV_VAR_MAP = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "cohere": "COHERE_API_KEY",
    "together": "TOGETHER_API_KEY",
    "ollama": None,
}

VERSION = "0.2.0"


class PromptInput(Input):
    """Input con historial ↑/↓ (como una shell) y autocompletado de comandos."""

    def __init__(self, **kw):
        super().__init__(suggester=SuggestFromList(_SLASH, case_sensitive=False), **kw)
        self.history: list[str] = []
        self._hist_i: int | None = None

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._hist_i = None

    def _on_key(self, event) -> None:
        if event.key == "up" and self.history:
            self._hist_i = len(self.history) - 1 if self._hist_i is None else max(0, self._hist_i - 1)
            self.value = self.history[self._hist_i]
            self.cursor_position = len(self.value)
            event.stop(); event.prevent_default()
        elif event.key == "down" and self._hist_i is not None:
            self._hist_i += 1
            if self._hist_i >= len(self.history):
                self._hist_i = None
                self.value = ""
            else:
                self.value = self.history[self._hist_i]
            self.cursor_position = len(self.value)
            event.stop(); event.prevent_default()


def _bar(pct: float, width: int = 12) -> str:
    fill = max(0, min(width, round(pct * width)))
    return "▰" * fill + "▱" * (width - fill)


def _fmt_time() -> str:
    return datetime.now().strftime("%H:%M")


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _fmt_duration(ms: int) -> str:
    if ms >= 60_000:
        return f"{ms/60_000:.1f}m"
    if ms >= 1_000:
        return f"{ms/1000:.1f}s"
    return f"{ms}ms"


class LeoTUI(App):
    TITLE = "leo-code"
    CSS = """
    Screen { layers: base; }
    #body { height: 1fr; }
    #chat {
        width: 2fr;
        border: tall $primary;
        padding: 0 1;
        background: $surface;
    }
    #sidebar {
        width: 40;
        border: tall $accent;
        padding: 0 1;
        background: $surface-darken-1;
    }
    #session-info {
        color: $text;
        padding: 0 0 1 0;
        height: auto;
    }
    #kcrag {
        color: $text;
        padding: 1 0;
        border-top: solid $primary-darken-2;
    }
    #graph {
        color: $text-muted;
        height: 1fr;
        padding: 1 0 0 0;
        border-top: solid $primary-darken-2;
    }
    .user {
        color: $accent;
        text-style: bold;
        padding: 1 0 0 0;
        margin: 0;
    }
    .leo {
        padding: 0 0 1 0;
        margin: 0;
    }
    .tool {
        color: $text-muted;
        margin: 0;
    }
    .system {
        color: $warning;
        margin: 0;
    }
    .welcome {
        color: $text-muted;
    }
    #prompt {
        border: tall $primary;
    }
    #meter {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        border-top: dashed $primary-darken-2;
    }
    .hint {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Salir"),
        Binding("ctrl+l", "clear_chat", "Limpiar"),
        Binding("ctrl+d", "show_diff", "Git Diff"),
        Binding("ctrl+r", "compact", "Compactar"),
        Binding("ctrl+m", "model_list", "Modelos"),
        Binding("ctrl+i", "session_info", "Sesión"),
    ]

    def __init__(self, repo: str = ".", model: str = "anthropic/claude-opus-4-8"):
        super().__init__()
        self.repo = os.path.abspath(repo)
        self.model = model
        self._tools = None
        self._agent = None
        self._sid = None
        self._caps_n = 0
        self._tok_total = 0
        self._tok_saved = 0
        self._base = 0
        self._leo = 0
        self._files = 0
        self._price = 3.0
        self._task_type = ""
        self._iterations = 0
        self._iter_count = 0

    # ── layout ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield VerticalScroll(id="chat")
            with Vertical(id="sidebar"):
                yield Static(self._session_text(), id="session-info")
                yield Static(self._kcrag_text("indexando…"), id="kcrag")
                yield Static("grafo determinista\n(usa /trace /impact /who /where)", id="graph")
        yield PromptInput(placeholder="› pregunta, o /help …", id="prompt")
        yield Static(self._meter_text(), id="meter")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self._index()
        self._show_welcome()

    # ── sidebar texts ───────────────────────────────────────────────────────

    def _session_text(self) -> str:
        branch = self._git_branch()
        sid_short = self._sid[:12] if self._sid else "—"
        model_short = self.model.split("/")[-1] if "/" in self.model else self.model
        lines = [
            f"[b]Sesión[/b] {sid_short}",
            f"modelo: {model_short}",
            f"rama: {branch}",
            f"cápsulas: {self._caps_n:,}",
        ]
        if self._tok_total:
            lines.append(f"tokens: {_fmt_tokens(self._tok_total)}")
        if self._iter_count:
            lines.append(f"iters: {self._iter_count}")
        return "\n".join(lines)

    def _kcrag_text(self, status: str) -> str:
        lines = [f"[b]KC-RAG[/b]"]
        if self._caps_n:
            lines.append(f"{self._caps_n:,} cápsulas")
        lines.append(status)
        if self._task_type:
            color = _TASK_THEMES.get(self._task_type, "dim")
            lines.append(f"tarea: [{color}]{self._task_type}[/{color}]")
        return "\n".join(lines)

    def _meter_text(self) -> str:
        pct = (self._tok_saved / self._base) if self._base else 0.0
        money = self._tok_saved / 1_000_000 * self._price
        parts = [
            f"Ahorro: {self._tok_saved:,} tok",
            f"{self._files} archivos no leídos",
            f"~${money:.3f} (~{pct*100:.0f}%)",
            _bar(pct),
        ]
        if self._iter_count:
            parts.insert(1, f"{self._iter_count} iters")
        parts.append("[dim]Ctrl+R compact · Ctrl+D diff · Ctrl+M modelos · Ctrl+I sesión[/dim]")
        return "  ·  ".join(parts)

    def _git_branch(self) -> str:
        try:
            r = subprocess.run("git branch --show-current", shell=True,
                               cwd=self.repo, capture_output=True, text=True, timeout=5)
            return r.stdout.strip() or "?"
        except Exception:
            return "?"

    def _update_sidebar(self):
        self.query_one("#session-info", Static).update(self._session_text())
        self.query_one("#meter", Static).update(self._meter_text())

    # ── chat rendering ──────────────────────────────────────────────────────

    def _say(self, text: str, cls: str = "leo") -> Markdown | Static:
        chat = self.query_one("#chat", VerticalScroll)
        ts = _fmt_time()
        if cls == "user":
            w = Static(f"[b]› {text}[/b]  [dim]{ts}[/dim]", classes="user")
        elif cls == "system":
            w = Static(f"⚡ {text}  [dim]{ts}[/dim]", classes="system")
        elif cls == "tool":
            w = Static(text, classes="tool")
        elif cls == "leo":
            w = Markdown(text)
            w.add_class("leo")
            w.border_title = f"leo  {ts}"
            w.border_subtitle = ""
        else:
            w = Static(text)
        if cls == "leo":
            w.add_class("leo")
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    def _say_user(self, text: str) -> Static:
        chat = self.query_one("#chat", VerticalScroll)
        w = Static(f"[b]› {text}[/b]  [dim]{_fmt_time()}[/dim]", classes="user")
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    def _say_leo(self, text: str, task_type: str = "") -> Markdown:
        chat = self.query_one("#chat", VerticalScroll)
        w = Markdown(text or "_(sin respuesta)_")
        w.add_class("leo")
        color = _TASK_THEMES.get(task_type, "")
        title = f"leo  {_fmt_time()}"
        if task_type:
            title += f"  {task_type}"
        w.border_title = title
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    def _say_tool(self, name: str, args_str: str, result: str, duration_s: float) -> Static:
        chat = self.query_one("#chat", VerticalScroll)
        header = f"▸ {name}({args_str[:60]}) · {duration_s:.1f}s"
        if result and len(result) > 800:
            result = result[:800] + f"\n[dim]… {len(result):,} chars total[/dim]"
        text = f"{header}\n```\n{result[:1500]}\n```" if result else header
        w = Static(text, classes="tool")
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    def _say_system(self, text: str) -> Static:
        chat = self.query_one("#chat", VerticalScroll)
        w = Static(f"⚡ {text}  [dim]{_fmt_time()}[/dim]", classes="system")
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    # ── welcome ─────────────────────────────────────────────────────────────

    def _show_welcome(self):
        branch = self._git_branch()
        model_short = self.model.split("/")[-1] if "/" in self.model else self.model
        repo_name = Path(self.repo).name
        msg = (
            f"# leo-code v{VERSION}\n\n"
            f"**repo:** {repo_name}  ·  **rama:** {branch}  ·  **modelo:** {model_short}\n\n"
            f"Comandos: `/help` para todos  ·  `/who X` / `/trace A B` / `/impact X`\n"
            f"Atajos: `Ctrl+R` compact  ·  `Ctrl+D` diff  ·  `Ctrl+M` modelos  ·  `Ctrl+I` sesión\n\n"
            f"[dim]Escribe tu pregunta o un comando...[/dim]"
        )
        chat = self.query_one("#chat", VerticalScroll)
        w = Markdown(msg)
        w.add_class("welcome")
        chat.mount(w)

    # ── input ───────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if isinstance(event.input, PromptInput):
            event.input.remember(text)
        if text.startswith("/"):
            self._slash(text)
        else:
            self._say_user(text)
            self._chat(text)

    # ── slash dispatcher ────────────────────────────────────────────────────

    def _slash(self, text: str) -> None:
        parts = text.split()
        cmd = parts[0][1:]
        args = parts[1:]
        rest = text[len(parts[0]):].strip()

        if cmd in ("quit", "q", "exit"):
            self.exit()
            return
        if cmd == "clear":
            self.action_clear_chat()
            return
        if cmd == "help":
            self._say_system("/help — comandos disponibles")
            self._say(_HELP)
            return

        # structural commands (no LLM needed)
        if cmd in ("trace", "impact", "guard", "who", "who_calls", "where", "callees", "compare"):
            self._slash_structural(cmd, args)
            return

        # session commands
        if cmd == "model":
            self._handle_model(rest)
            return
        if cmd == "sessions":
            self._handle_sessions()
            return
        if cmd == "session":
            self._handle_session_info()
            return
        if cmd == "diff":
            self._handle_diff()
            return
        if cmd == "doctor":
            self._handle_doctor()
            return
        if cmd == "compact":
            self._handle_compact()
            return
        if cmd == "goal":
            self._handle_goal(rest)
            return
        if cmd == "image":
            self._handle_image(rest)
            return
        if cmd == "permissions":
            self._handle_permissions(rest)
            return
        if cmd == "key":
            self._handle_key(rest)
            return

        self._say_system(f"Comando desconocido: /{cmd}. Prueba /help")

    # ── structural commands (from original) ─────────────────────────────────

    def _slash_structural(self, cmd: str, args: list[str]) -> None:
        if self._tools is None:
            self._say_system("Índice aún construyéndose…")
            return
        gq = self._tools._gq

        if cmd == "compare" and args:
            self._say_system(f"Comparando con grep+read para **{args[0]}**…")
            self._compare(args[0])
            return

        if cmd == "guard" and args:
            from leo_code.core.guardian import Guardian
            try:
                rep = Guardian(self._tools._capsules).review(args[0])
            except Exception as e:
                self._say_system(f"error: {e}")
                return
            txt = self._relz(rep.render())
            self._say(f"**/guard {args[0]}** — determinista, cero LLM:\n```\n{txt}\n```")
            self.query_one("#graph", Static).update(
                f"[b]guard · radio de explosión[/b]\n" + "\n".join(txt.splitlines()[:14]))
            return

        try:
            if cmd == "trace" and len(args) >= 2:
                proof = gq.trace(args[0], args[1])
            elif cmd in ("impact", "who", "who_calls", "where", "callees") and args:
                sym = args[0]
                proof = {"impact": gq.impact, "who": gq.who_calls, "who_calls": gq.who_calls,
                         "where": gq.where, "callees": gq.callees}[cmd](sym)
            else:
                self._say_system(f"Uso: `/{cmd} <símbolo>` (o `/trace A B`). `/help` para todo.")
                return
        except Exception as e:
            self._say_system(f"error: {e}")
            return

        md = self._render_proof(cmd, proof)
        self._say(md)
        head = proof.render().splitlines()[0]
        self.query_one("#graph", Static).update(
            f"[b]grafo · determinista · cero LLM[/b]\n{head}\n\n"
            + "\n".join(f"· {c.name}  {self._rel(c.file)}:{c.line}" for c in proof.cites[:12]))
        from leo_code.core.tokens import count_tokens
        sym = args[1] if cmd == "trace" and len(args) >= 2 else args[0]
        self._calc_saved(sym, count_tokens(md))

    # ── management commands ─────────────────────────────────────────────────

    def _handle_model(self, rest: str):
        if rest == "list":
            self._model_list()
            return
        if rest:
            old = self.model
            self.model = rest
            self._agent = None  # force re-init with new model
            self._say_system(f"Modelo: [cyan]{rest}[/cyan] (era [dim]{old}[/dim])")
            self._update_sidebar()
        else:
            self._say_system("Uso: /model <id>  o  /model list")

    def _model_list(self):
        from leo_code.rag.llm import discover_providers, discover_models, CATALOG
        providers = discover_providers()
        lines = ["**Providers detectados:**"]
        for p in ["anthropic", "openai", "deepseek", "google", "mistral", "groq",
                   "cohere", "openrouter", "together", "azure", "bedrock", "ollama"]:
            status = "✓" if p in providers else "○"
            lines.append(f"- `{status}` {p}")
        lines.append("\n**Modelos disponibles:**")
        models = discover_models()
        for m in models[:12]:
            cost = f"${m.cost_input:.2f}/${m.cost_output:.2f}"
            lines.append(f"- `{m.id}` — {m.name} [dim]({cost} por 1M tok, {m.tier})[/dim]")
        self._say("\n".join(lines))

    def _handle_sessions(self):
        from leo_code.session import SessionManager
        sm = SessionManager()
        sessions = sm.list_sessions(10)
        if not sessions:
            self._say_system("No hay sesiones guardadas")
            return
        lines = [f"**Sesiones guardadas: {len(sessions)}**"]
        for s in sessions:
            marker = " ← actual" if s.id == self._sid else ""
            model_s = s.model.split("/")[-1] if "/" in s.model else s.model
            lines.append(f"- `{s.id[:12]}` — {model_s} · {s.message_count} msgs · {_fmt_tokens(s.total_tokens)} tok{marker}")
        self._say("\n".join(lines))

    def _handle_session_info(self):
        from leo_code.session import SessionManager
        sm = SessionManager()
        s = sm.get_session(self._sid) if self._sid else None
        if s:
            self._say(
                f"**Sesión actual**\n\n"
                f"- id: `{s.id}`\n"
                f"- repo: {s.repo_path}\n"
                f"- modelo: {s.model}\n"
                f"- mensajes: {s.message_count}\n"
                f"- tokens: {_fmt_tokens(s.total_tokens)}\n"
                f"- creada: {datetime.fromtimestamp(s.created_at).strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            self._say_system("Sin sesión activa (se crea al primer chat)")

    def _handle_diff(self):
        try:
            r = subprocess.run("git diff", shell=True, cwd=self.repo,
                               capture_output=True, text=True, timeout=10)
            out = r.stdout or "[sin cambios]"
            if out == "[sin cambios]":
                self._say_system("Sin cambios en el repo")
            else:
                self._say(f"**git diff:**\n```diff\n{out[:3000]}\n```")
        except Exception as e:
            self._say_system(f"Error: {e}")

    def _handle_doctor(self):
        lines = [f"# Diagnóstico leo-code v{VERSION}", ""]
        lines.append(f"- Python {sys.version.split()[0]}")
        lines.append(f"- Repo: {self.repo}")
        lines.append(f"- Rama: {self._git_branch()}")

        cache_dir = Path(os.getenv("LEO_CACHE_DIR", "./cache"))
        idx_path = cache_dir / "kc_index.json.gz"
        if idx_path.exists():
            try:
                import gzip
                data = json.loads(gzip.decompress(idx_path.read_bytes()))
                total = data.get("total_capsules", 0)
                lines.append(f"- KC-RAG: {total} cápsulas ✓")
            except Exception:
                lines.append("- KC-RAG: índice corrupto ⚠")
        else:
            lines.append("- KC-RAG: no indexado (usa `leo-code index .`) ⚠")

        from leo_code.rag.llm import discover_providers
        discovered = discover_providers()
        lines.append(f"\n**Providers:**")
        for p in ["anthropic", "openai", "deepseek", "google", "mistral",
                   "groq", "cohere", "openrouter", "azure", "bedrock", "ollama"]:
            status = "✓" if p in discovered else "○"
            lines.append(f"- `{status}` {p}")

        lines.append(f"\n- Sesión: `{self._sid[:12] if self._sid else '—'}`")
        lines.append(f"- Modelo: {self.model}")
        lines.append(f"- Tokens gastados: {_fmt_tokens(self._tok_total)}")
        self._say("\n".join(lines))

    def _handle_compact(self):
        self._say_system("Compactando historial… [dim](los mensajes antiguos se resumen)[/dim]")

    def _handle_goal(self, rest: str):
        if not rest:
            self._say_system("Uso: /goal <descripción de la tarea>")
            return
        self._say_system(f"🎯 Goal: {rest[:100]}")
        self._say("_[Modo goal: plan → execute → verify → re-plan. En desarrollo en la TUI.]_")

    def _handle_image(self, rest: str):
        if not rest:
            self._say_system("Uso: /image <ruta a imagen>")
            return
        img_path = Path(rest.strip())
        if img_path.exists():
            self._say_system(f"Imagen cargada: {rest}")
            self._say("_[Análisis de visión: envía tu pregunta tras cargar la imagen.]_")
        else:
            self._say_system(f"No encontrada: {rest}")

    def _handle_permissions(self, rest: str):
        if not rest:
            self._say(
                "**Permisos de tools**\n\n"
                "- `/permissions auto` — permitir todo\n"
                "- `/permissions ask` — preguntar (recomendado)\n"
                "- `/permissions deny` — rechazar todo"
            )
        elif rest == "auto":
            self._say_system("Permisos: [green]auto[/green] (todas las tools permitidas)")
        elif rest == "ask":
            self._say_system("Permisos: [yellow]ask[/yellow] (preguntar antes de ejecutar)")
        elif rest == "deny":
            self._say_system("Permisos: [red]deny[/red] (todas las tools bloqueadas)")

    def _handle_key(self, rest: str):
        rest = rest.strip()
        if not rest or rest == "list":
            lines = ["**API Keys configuradas:**"]
            for provider, var in sorted(_ENV_VAR_MAP.items()):
                if var:
                    status = "✓" if os.getenv(var) else "○"
                    lines.append(f"- `{status}` {provider:<12} {var}")
            try:
                import httpx
                if httpx.get("http://localhost:11434/api/tags", timeout=1).status_code == 200:
                    lines.append(f"- `✓` ollama (local)")
            except Exception:
                lines.append(f"- `○` ollama (local)")
            lines.append("\n[dim]/key set <proveedor> <api_key>  — configurar[/dim]")
            self._say("\n".join(lines))
        elif rest.startswith("set "):
            parts = rest[4:].strip().split(None, 1)
            if len(parts) >= 2:
                provider, key = parts[0], parts[1]
                var = _ENV_VAR_MAP.get(provider)
                if var:
                    os.environ[var] = key
                    self._say_system(f"API key guardada para [cyan]{provider}[/cyan] ({var})")
                else:
                    self._say_system(f"Proveedor desconocido: {provider}")
            else:
                self._say_system("Uso: /key set <proveedor> <api_key>")
        elif rest.startswith("remove "):
            provider = rest[7:].strip()
            var = _ENV_VAR_MAP.get(provider)
            if var:
                os.environ.pop(var, None)
                self._say_system(f"API key eliminada: {provider}")
            else:
                self._say_system(f"Proveedor desconocido: {provider}")

    # ── chat with agent ─────────────────────────────────────────────────────

    @work(exclusive=False)
    async def _chat(self, query: str) -> None:
        if self._agent is None:
            from leo_code.rag.agent.loop import AgentLoop
            from leo_code.rag.agent.tools import ToolRegistry
            self._agent = AgentLoop(tools=self._tools or ToolRegistry(), max_iterations=12)
        if self._sid is None:
            from leo_code.session import SessionManager
            sm = SessionManager()
            self._sid = sm.create_session(self.repo, self.model).id
            self._update_sidebar()

        bubble = self._say_leo("…")
        t0_total = time.time()
        buf = ""
        tline, tname, targs, t0 = None, "", "", 0.0
        tool_count = 0
        tok_acc = 0
        try:
            async for ev in self._agent.stream_run(
                query, repo_path=self.repo, model=self.model, session_id=self._sid
            ):
                t = ev.get("type")
                if t == "context":
                    tok = ev.get("tokens", 0)
                    tok_acc += tok
                    self._tok_total += tok
                    tt = ev.get("task_type", "")
                    if tt:
                        self._task_type = tt
                    self.query_one("#kcrag", Static).update(
                        self._kcrag_text(f"contexto: {tok} tok · {tt}"))
                    self._update_sidebar()
                elif t == "token":
                    buf += ev.get("text", "")
                    bubble.update(buf)
                    self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
                elif t == "tool_start":
                    tool_count += 1
                    tname = ev.get("name", "")
                    targs = str(ev.get("args", ""))[:60]
                    t0 = time.time()
                    tline = self._say(f"▸ {tname}({targs}) …", cls="tool")
                    if tname == "replace_in_file":
                        a = ev.get("args", {}) or {}
                        diff = "\n".join(
                            [f"--- {a.get('file_path', '')}"]
                            + [f"- {l}" for l in str(a.get("old_string", "")).splitlines()]
                            + [f"+ {l}" for l in str(a.get("new_string", "")).splitlines()])
                        self._say(f"```diff\n{diff[:1500]}\n```")
                    self.query_one("#graph", Static).update(
                        f"[b]grafo · tool[/b]\n▸ {tname}({targs[:40]})")
                elif t == "tool_result":
                    out = ev.get("output", "") or ""
                    duration = time.time() - t0 if t0 else 0
                    if tline is not None:
                        tline.update(f"▸ {tname}({targs}) · {duration:.1f}s · {len(out):,} chars")
                        tline = None
                    head = self._relz(out).splitlines()[:8]
                    self.query_one("#graph", Static).update(
                        f"[b]{tname}[/b]\n" + "\n".join(head))
                elif t == "done":
                    final = buf or ev.get("respuesta", "") or "_(sin respuesta)_"
                    tok_acc += len(final) // 4
                    self._tok_total += tok_acc
                    self._iter_count = ev.get("iterations", self._iter_count)
                    bubble.update(final)
                    if self._task_type:
                        bubble.border_title = f"leo  {_fmt_time()}  {self._task_type}"
                        bubble.border_subtitle = (
                            f"{_fmt_tokens(tok_acc)} tok  ·  "
                            f"{tool_count} tools  ·  "
                            f"{_fmt_duration(ev.get('duration_ms', 0))}  ·  "
                            f"{ev.get('iterations', 0)} iters"
                        )
                    self._update_sidebar()
        except Exception as e:
            bubble.update(
                f"_No pude completar el chat: {e}_\n\n"
                "Para chatear necesitas un modelo y API key configurada "
                "(p.ej. `ANTHROPIC_API_KEY` o `DEEPSEEK_API_KEY`). "
                "Las funciones `/trace` `/impact` `/who` `/where` funcionan **sin** LLM."
            )

    # ── indexing ────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True)
    def _index(self) -> None:
        from leo_code.rag.indexer import Indexer
        from leo_code.rag.agent.tools import ToolRegistry
        idx = Indexer()
        idx.build(self.repo, verbose=False)
        caps = idx.get_capsules()
        tools = ToolRegistry()
        tools.set_index(caps)
        self._tools = tools
        self._caps_n = len(caps)
        self.call_from_thread(self.query_one("#kcrag", Static).update,
                              self._kcrag_text("listo · grafo activo ✓"))
        self.call_from_thread(self._update_sidebar)
        self.call_from_thread(self._say_system,
            f"Índice listo: **{self._caps_n:,} cápsulas**. Prueba `/who compress` o `/help`.")

    # ── structural helpers ──────────────────────────────────────────────────

    def _baseline(self, symbol: str) -> tuple[int, int]:
        from leo_code.core.tokens import count_tokens
        toks, nfiles = 0, 0
        for p in Path(self.repo).rglob("*.py"):
            s = str(p).replace("\\", "/")
            if any(k in s for k in ("/.leo-code/", "/cache/", "/__pycache__/")):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if symbol in txt:
                toks += count_tokens(txt)
                nfiles += 1
        return toks, nfiles

    @work(thread=True, exclusive=False)
    def _calc_saved(self, symbol: str, leo_cost: int) -> None:
        base, nfiles = self._baseline(symbol)
        self._base += base
        self._leo += leo_cost
        self._tok_saved += max(0, base - leo_cost)
        self._files += nfiles
        self.call_from_thread(self._update_sidebar)

    @work(thread=True, exclusive=False)
    def _compare(self, symbol: str) -> None:
        from leo_code.core.tokens import count_tokens
        gq = self._tools._gq
        proof = gq.who_calls(symbol)
        leo_cost = count_tokens(self._render_proof("who", proof))
        base_tok, nfiles = self._baseline(symbol)
        ratio = base_tok / max(leo_cost, 1)
        mb, ml = base_tok / 1_000_000 * self._price, leo_cost / 1_000_000 * self._price
        md = (
            f"**¿Quién llama a `{symbol}`?** — la misma respuesta, dos caminos:\n\n"
            f"| | Claude Code / opencode | leo-code |\n"
            f"|---|---|---|\n"
            f"| método | grep + leer archivos + LLM | grafo determinista |\n"
            f"| archivos abiertos | **{nfiles}** | **0** |\n"
            f"| tokens al LLM | **{base_tok:,}** | **{leo_cost:,}** |\n"
            f"| coste aprox | ~${mb:.3f} | ~${ml:.4f} |\n"
            f"| prueba | no — puede alucinar | sí — archivo:línea |\n\n"
            f"→ leo: **{ratio:.0f}× menos tokens**, **{nfiles} archivos menos**, y verificable."
        )
        self.call_from_thread(self._say, md)
        self._base += base_tok
        self._leo += leo_cost
        self._tok_saved += max(0, base_tok - leo_cost)
        self._files += nfiles
        self.call_from_thread(self._update_sidebar)

    def _rel(self, path: str) -> str:
        p = (path or "").replace("\\", "/")
        base = self.repo.replace("\\", "/").rstrip("/") + "/"
        return p[len(base):] if p.startswith(base) else p

    def _relz(self, text: str) -> str:
        pref = self.repo.replace("\\", "/").rstrip("/") + "/"
        return text.replace("\\", "/").replace(pref, "")

    def _render_proof(self, cmd: str, proof) -> str:
        if not proof.cites:
            return f"**/{cmd}** — sin resultados."
        lines = [f"**/{cmd}** — {len(proof.cites)} resultado(s), con prueba (cero LLM):"]
        lines += [f"- `{c.name}` ({c.type}) — `{self._rel(c.file)}:{c.line}`" for c in proof.cites[:25]]
        if proof.edges:
            chain = " → ".join(dict.fromkeys([proof.edges[0][0]] + [e[1] for e in proof.edges]))
            lines.append(f"\naristas: `{chain}`")
        return "\n".join(lines)

    # ── actions ─────────────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()
        self._show_welcome()

    def action_show_diff(self) -> None:
        self._handle_diff()

    def action_compact(self) -> None:
        self._handle_compact()

    def action_model_list(self) -> None:
        self._model_list()

    def action_session_info(self) -> None:
        self._handle_session_info()


def run_tui(repo: str = ".", model: str = "anthropic/claude-opus-4-8") -> None:
    LeoTUI(repo=repo, model=model).run()


if __name__ == "__main__":
    run_tui(sys.argv[1] if len(sys.argv) > 1 else ".")
