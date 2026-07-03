"""TUI Cockpit de leo-code (Textual): chat + panel de contexto en vivo + grafo.

Layout full-screen:
  ┌ chat ───────────────┬ contexto ──────┐
  │ conversación         │ KC-RAG (tokens) │
  │ (markdown + código)  │ grafo (vivo)    │
  ├ input ───────────────┴────────────────┤
  │ › …                     medidor tokens │
  └────────────────────────────────────────┘

Lo distintivo: los comandos ESTRUCTURALES son DETERMINISTAS y no gastan LLM —
funcionan aunque no tengas API key:
  /trace A B   · camino de llamadas A→B con prueba (archivo:línea)
  /impact X    · qué se rompe si cambias X
  /who X       · quién llama a X
  /where X     · dónde se define X
  /callees X   · a qué llama X
Texto normal → chat con el agente (necesita un modelo: --model, ANTHROPIC_API_KEY…).

Arranque:  leo-code tui   (o: python -m leo_code.rag.cli.tui)
"""

from __future__ import annotations

import os
import time

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual import work

_HELP = (
    "**Comandos** (deterministas, cero LLM):\n"
    "- `/trace A B` — camino de llamadas A→B, con prueba\n"
    "- `/impact X` — qué se rompe si cambias X\n"
    "- `/guard X` — radio de explosión + qué afectados están SIN test (antes de editar)\n"
    "- `/who X` — quién llama a X · `/callees X` — a qué llama X\n"
    "- `/where X` — dónde se define X\n"
    "- `/compare X` — lado-a-lado: leo vs grep+read (tokens, archivos, $)\n"
    "- `/help` · `/clear` · `/quit`\n\n"
    "Cualquier otro texto → chat con el agente. ↑/↓ recuperan el historial."
)

_SLASH = ["/trace ", "/impact ", "/guard ", "/who ", "/callees ", "/where ",
          "/compare ", "/help", "/clear", "/quit"]


class PromptInput(Input):
    """Input con historial ↑/↓ (como una shell) y autocompletado de comandos."""

    def __init__(self, **kw):
        super().__init__(suggester=SuggestFromList(_SLASH, case_sensitive=False), **kw)
        self.history: list[str] = []
        self._hist_i: int | None = None  # None = escribiendo nuevo

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
    """Barra ▰▱ para el medidor de tokens (pct = fracción ahorrada 0..1)."""
    fill = max(0, min(width, round(pct * width)))
    return "▰" * fill + "▱" * (width - fill)


class LeoTUI(App):
    TITLE = "leo-code"
    CSS = """
    Screen { layers: base; }
    #body { height: 1fr; }
    #chat {
        width: 2fr; border: round $primary; padding: 0 1;
        background: $surface;
    }
    #sidebar { width: 38; border: round $accent; padding: 0 1; }
    #kcrag { color: $text; padding: 0 0 1 0; }
    #graph { color: $text-muted; height: 1fr; }
    .user { color: $accent; text-style: bold; padding: 1 0 0 0; }
    .leo  { padding: 0 0 1 0; }
    .tool { color: $text-muted; }
    #prompt { border: round $primary; }
    #meter { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [("ctrl+c", "quit", "salir"), ("ctrl+l", "clear", "limpiar")]

    def __init__(self, repo: str = ".", model: str = "anthropic/claude-opus-4-8"):
        super().__init__()
        self.repo = os.path.abspath(repo)
        self.model = model
        self._tools = None       # ToolRegistry (cerebro determinista para slash-cmds)
        self._agent = None       # AgentLoop (chat)
        self._caps_n = 0
        self._tok_total = 0      # tokens gastados (chat)
        self._saved = 0          # tokens AHORRADOS vs leer archivos enteros
        self._base = 0           # baseline acumulado (lo que gastaría grep+read)
        self._leo = 0            # coste leo acumulado (para el %)
        self._files = 0          # archivos que el otro agente NO tuvo que abrir
        self._price = 3.0        # $/1M tokens de entrada (estimación, ajustable)

    # ---- layout ----
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield VerticalScroll(id="chat")
            with Vertical(id="sidebar"):
                yield Static(self._kcrag_text("indexando…"), id="kcrag")
                yield Static("grafo determinista\n(usa /trace /impact /who /where)", id="graph")
        yield PromptInput(placeholder="› pregunta, o /help …", id="prompt")
        yield Static(self._meter_text(), id="meter")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self._index()  # construye el índice estructural en background

    # ---- estado / textos ----
    def _kcrag_text(self, status: str) -> str:
        return (f"[b]KC-RAG[/b]\n{self._caps_n:,} cápsulas\n{status}\n"
                f"modelo: {self.model.split('/')[-1]}")

    def _meter_text(self) -> str:
        pct = (self._saved / self._base) if self._base else 0.0
        money = self._saved / 1_000_000 * self._price
        return (f"AHORRADOS: {self._saved:,} tok  ·  {self._files} archivos no leídos  ·  "
                f"~${money:.3f}  (~{pct*100:.0f}% vs leer archivos) {_bar(pct)}")

    def _baseline(self, symbol: str) -> tuple[int, int]:
        """Lo que un agente grep+read gastaría para responder sobre `symbol`:
        (tokens, nº de archivos que abriría). Es el contrafactual visible."""
        from pathlib import Path
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
                toks += count_tokens(txt); nfiles += 1
        return toks, nfiles

    def _say(self, text: str, cls: str = "leo") -> Markdown | Static:
        chat = self.query_one("#chat", VerticalScroll)
        w = Markdown(text) if cls == "leo" else Static(text, classes=cls)
        if cls == "leo":
            w.add_class("leo")
        chat.mount(w)
        chat.scroll_end(animate=False)
        return w

    def _relz(self, text: str) -> str:
        """Todas las rutas del texto relativas al repo (citas legibles)."""
        pref = self.repo.replace("\\", "/").rstrip("/") + "/"
        return text.replace("\\", "/").replace(pref, "")

    # ---- índice estructural (cerebro determinista, sin LLM) ----
    @work(thread=True, exclusive=True)
    def _index(self) -> None:
        from leo_code.rag.indexer import Indexer
        from leo_code.rag.agent.tools import ToolRegistry
        idx = Indexer()
        idx.build(self.repo, verbose=False)
        caps = idx.get_capsules()
        tools = ToolRegistry()
        tools.set_index(caps)          # cablea GraphQuery
        self._tools = tools
        self._caps_n = len(caps)
        self.call_from_thread(self.query_one("#kcrag", Static).update,
                              self._kcrag_text("listo · grafo activo ✓"))
        self.call_from_thread(self._say,
            f"Índice listo: **{self._caps_n:,} cápsulas**. Prueba `/who compress` o `/help`.")

    # ---- input ----
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
            self._say(f"› {text}", cls="user")
            self._chat(text)

    def _slash(self, text: str) -> None:
        parts = text.split()
        cmd, args = parts[0][1:], parts[1:]
        if cmd in ("quit", "q", "exit"):
            self.exit(); return
        if cmd == "clear":
            self.action_clear(); return
        if cmd == "help":
            self._say(_HELP); return
        if self._tools is None:
            self._say("_Índice aún construyéndose…_"); return
        gq = self._tools._gq
        if cmd == "compare" and args:
            self._say(f"› comparando con grep+read para **{args[0]}**…")
            self._compare(args[0]); return
        if cmd == "guard" and args:
            # Radio de explosión + cobertura ANTES de editar: el semáforo de riesgo.
            from leo_code.core.guardian import Guardian
            try:
                rep = Guardian(self._tools._capsules).review(args[0])
            except Exception as e:
                self._say(f"_error: {e}_"); return
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
                self._say(f"_uso: `/{cmd} <símbolo>` (o `/trace A B`). `/help` para todo._"); return
        except Exception as e:
            self._say(f"_error: {e}_"); return
        md = self._render_proof(cmd, proof)
        self._say(md)
        # ilumina el panel de grafo con la última operación + prueba
        head = proof.render().splitlines()[0]
        self.query_one("#graph", Static).update(
            f"[b]grafo · determinista · cero LLM[/b]\n{head}\n\n"
            + "\n".join(f"· {c.name}  {self._rel(c.file)}:{c.line}" for c in proof.cites[:12]))
        # contabiliza tokens AHORRADOS vs un agente grep+lee-archivos (en background)
        from leo_code.core.tokens import count_tokens
        sym = args[1] if cmd == "trace" and len(args) >= 2 else args[0]
        self._calc_saved(sym, count_tokens(md))

    @work(thread=True, exclusive=False)
    def _calc_saved(self, symbol: str, leo_cost: int) -> None:
        """Acumula el ahorro (baseline grep+read − coste de leo) y los archivos no leídos."""
        base, nfiles = self._baseline(symbol)
        self._base += base
        self._leo += leo_cost
        self._saved += max(0, base - leo_cost)
        self._files += nfiles
        self.call_from_thread(self.query_one("#meter", Static).update, self._meter_text())

    @work(thread=True, exclusive=False)
    def _compare(self, symbol: str) -> None:
        """Lado-a-lado anti-humo: la MISMA pregunta resuelta por grep+read (Claude
        Code/opencode) vs el grafo de leo. Hace visible el contrafactual."""
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
        self._base += base_tok; self._leo += leo_cost
        self._saved += max(0, base_tok - leo_cost); self._files += nfiles
        self.call_from_thread(self.query_one("#meter", Static).update, self._meter_text())

    def _rel(self, path: str) -> str:
        """Path relativo al repo para que la prueba quede legible."""
        p = (path or "").replace("\\", "/")
        base = self.repo.replace("\\", "/").rstrip("/") + "/"
        return p[len(base):] if p.startswith(base) else p

    def _render_proof(self, cmd: str, proof) -> str:
        if not proof.cites:
            return f"**/{cmd}** — sin resultados."
        lines = [f"**/{cmd}** — {len(proof.cites)} resultado(s), con prueba (cero LLM):"]
        lines += [f"- `{c.name}` ({c.type}) — `{self._rel(c.file)}:{c.line}`" for c in proof.cites[:25]]
        if proof.edges:
            chain = " → ".join(dict.fromkeys([proof.edges[0][0]] + [e[1] for e in proof.edges]))
            lines.append(f"\naristas: `{chain}`")
        return "\n".join(lines)

    # ---- chat con el agente (necesita LLM) ----
    @work(exclusive=False)
    async def _chat(self, query: str) -> None:
        if self._agent is None:
            from leo_code.rag.agent.loop import AgentLoop
            from leo_code.rag.agent.tools import ToolRegistry
            self._agent = AgentLoop(tools=self._tools or ToolRegistry(), max_iterations=12)
        bubble = self._say("…")
        buf = ""
        tline, tname, targs, t0 = None, "", "", 0.0
        try:
            async for ev in self._agent.stream_run(query, repo_path=self.repo, model=self.model):
                t = ev.get("type")
                if t == "context":
                    self._tok_total += ev.get("tokens", 0)
                    self.query_one("#kcrag", Static).update(
                        self._kcrag_text(f"contexto: {ev.get('tokens',0)} tok · {ev.get('task_type','')}"))
                    self.query_one("#meter", Static).update(self._meter_text())
                elif t == "token":
                    buf += ev.get("text", "")
                    bubble.update(buf)
                    self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
                elif t == "tool_start":
                    # línea de tool en el chat (viva): se completa con ms y tamaño al acabar
                    tname, targs, t0 = ev.get("name", ""), str(ev.get("args", ""))[:60], time.time()
                    tline = self._say(f"  ▸ {tname}({targs}) …", cls="tool")
                    if tname == "replace_in_file":
                        # el parche visible ANTES de aplicarse (como un mini code-review)
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
                    if tline is not None:
                        tline.update(f"  ▸ {tname}({targs}) · {time.time()-t0:.1f}s · {len(out):,} chars")
                        tline = None
                    head = self._relz(out).splitlines()[:8]
                    self.query_one("#graph", Static).update(
                        f"[b]{tname}[/b]\n" + "\n".join(head))
                elif t == "done":
                    bubble.update(buf or ev.get("respuesta", "") or "_(sin respuesta)_")
        except Exception as e:
            bubble.update(f"_No pude completar el chat: {e}_\n\n"
                          "Para chatear necesitas un modelo (p.ej. `ant auth login` para tu "
                          "suscripción Claude, o `ANTHROPIC_API_KEY`). Las funciones `/trace` "
                          "`/impact` `/who` `/where` funcionan **sin** LLM.")

    # ---- acciones ----
    def action_clear(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()


def run_tui(repo: str = ".", model: str = "anthropic/claude-opus-4-8") -> None:
    LeoTUI(repo=repo, model=model).run()


if __name__ == "__main__":
    import sys
    run_tui(sys.argv[1] if len(sys.argv) > 1 else ".")
