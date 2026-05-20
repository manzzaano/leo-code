"""leo-code CLI: agente de terminal con KC-RAG estructural.

Comandos:
    leo-code ask "refactor auth to async"    # Consulta directa
    leo-code chat                             # Modo conversacional multi-turn
    leo-code index .                          # Indexar repo
"""

import os
import sys
import signal
import asyncio
import click
from pathlib import Path

VERSION = "0.2.0"

class CancelToken:
    def __init__(self):
        self.cancelled = False

_cancel = CancelToken()

def _setup_signals():
    def handler(sig, frame):
        if not _cancel.cancelled:
            _cancel.cancelled = True
            print("\n⏎ Interrumpiendo...", flush=True)
    signal.signal(signal.SIGINT, handler)


_TASK_COLORS = {
    "debug": "red", "test_gen": "green", "audit": "yellow",
    "code_query": "blue", "code_gen": "cyan", "refactor": "magenta",
    "review": "bright_blue", "optimize": "bright_yellow",
    "search": "white", "onboard": "bright_cyan", "design_review": "purple",
    "code_edit": "orange1", "no_code": "dim",
}


@click.group()
@click.version_option(version=VERSION, prog_name="leo-code")
def cli():
    """leo-code — terminal agent con KC-RAG estructural.

    Model-agnostic (12 providers). 28 lenguajes. 15x menos tokens.
    """
    pass


def _render_stream(console, events, status, total_saved_ref):
    """Render streaming con markdown, syntax highlight, spinner, impacto."""
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn

    _buffer = ""
    _in_code = False
    _code_lang = ""
    _first_token = False

    for event in events:
        yield event  # for cancellation check
        etype = event["type"]

        if etype == "plugins":
            plugins = event.get("plugins", [])
            if plugins:
                running = [p for p in plugins if p.get("running")]
                console.print(f"[dim]  plugins: {', '.join(p['name'] for p in running)}[/dim]")

        elif etype == "skills":
            skills = event.get("skills", [])
            if skills:
                console.print(f"[dim]  skills: {', '.join(s['name'] for s in skills)}[/dim]")

        elif etype == "context":
            ttype = event.get("task_type", "")
            color = _TASK_COLORS.get(ttype, "dim")
            status.update_context(event.get("tokens", 0), ttype)
            console.print(f"[{color}]  ▸ KC-RAG · {event['tokens']} tok · {ttype}[/{color}]")

        elif etype == "token":
            if not _first_token:
                _first_token = True
                console.print()  # newline after spinner/KC-RAG info
            token = event["text"]
            _buffer += token

            if not _in_code and "```" in _buffer:
                parts = _buffer.split("```", 2)
                pre = parts[0].rstrip()
                if pre:
                    try:
                        console.print(Markdown(pre))
                    except Exception:
                        console.print(pre)
                if len(parts) >= 2:
                    _in_code = True
                    _code_lang = parts[1].split("\n")[0].strip() or "text"
                    _buffer = "\n".join(parts[1].split("\n")[1:]) if "\n" in parts[1] else ""

        elif etype == "done":
            if _in_code:
                _in_code = False
                if _buffer.strip():
                    try:
                        console.print(Syntax(_buffer.strip(), _code_lang, theme="monokai", line_numbers=True, background_color="default"))
                    except Exception:
                        console.print(_buffer.strip())
            elif _buffer.strip():
                try:
                    console.print(Markdown(_buffer.strip()))
                except Exception:
                    console.print(_buffer.strip())
            _buffer = ""

            # Impact bar
            dur = event.get("duration_ms", 0)
            tokens = event.get("total_tokens", 0)
            its = event.get("iterations", 0)
            saved = max(0, 20000 - tokens)
            status.end_query(tokens, its, dur, saved)
            _render_impact(console, tokens, saved, its, dur)
            total_saved_ref[0] += saved

        elif etype == "tool_start":
            if _in_code:
                _in_code = False
                if _buffer.strip():
                    try:
                        console.print(Syntax(_buffer.strip(), _code_lang, theme="monokai", line_numbers=True, background_color="default"))
                    except Exception:
                        console.print(_buffer.strip())
                _buffer = ""
            args_str = ", ".join(f"{k}={v}" for k, v in event.get("args", {}).items())[:100]
            console.print(f"\n[yellow]  🔧 {event['name']}({args_str})[/yellow]", highlight=False)

        elif etype == "tool_result":
            out = event.get("output", "")[:600]
            if out:
                if "diff" in event.get("name", ""):
                    console.print(Syntax(out, "diff", theme="monokai", background_color="default"))
                else:
                    console.print(f"  [dim]{out}[/dim]")


def _render_impact(console, tokens: int, saved: int, its: int, dur: int):
    from rich.table import Table
    ratio = min(saved / 20000, 1.0)
    bar = "█" * int(ratio * 30) + "░" * (30 - int(ratio * 30))
    color = "[green]" if ratio > 0.6 else ("[yellow]" if ratio > 0.3 else "[red]")
    console.print(f"\n  {bar} {color}{saved:,} tok ahorrados ({int(ratio*100)}% eficiencia)[/]")
    console.print(f"  [dim]{its} iters · {tokens} tok · {dur}ms[/dim]\n")


@cli.command()
@click.argument("query")
@click.option("--model", "-m", default="deepseek/deepseek-v4-flash",
              help="Modelo LLM (auto-detecta provider por env vars)")
@click.option("--repo", "-r", default=".", help="Ruta del repositorio")
@click.option("--no-rag", is_flag=True, help="Desactivar KC-RAG (solo LLM directo)")
@click.option("--image", "-i", multiple=True, type=click.Path(exists=True),
              help="Imagen(es) para análisis de visión (puede repetirse)")
def ask(query: str, model: str, repo: str, no_rag: bool, image: tuple[str]):
    """Consulta directa al agente con KC-RAG."""
    from rich.console import Console
    console = Console(highlight=False)
    _setup_signals()

    console.print(f"  [dim]repo: {Path(repo).resolve()}[/dim]")
    console.print(f"  [dim]modelo: {model}  |  KC-RAG: {'off' if no_rag else 'on'}[/dim]")
    if image:
        console.print(f"  [dim]imágenes: {len(image)}[/dim]")
    console.print()

    async def run():
        from leo_code.rag.agent.loop import AgentLoop
        agent = AgentLoop(max_iterations=12)
        agent.interrupt = False
        ts = [0]

        events = agent.stream_run(
            query, repo_path=repo, model=model, use_kc_rag=not no_rag,
            images=list(image) if image else None,
        )
        for event in _render_stream(console, events, None, ts):
            if _cancel.cancelled:
                agent.interrupt = True
            if event.get("type") == "done":
                break

    asyncio.run(run())


@cli.command()
@click.option("--model", "-m", default="deepseek/deepseek-v4-flash",
              help="Modelo LLM")
@click.option("--repo", "-r", default=".", help="Ruta del repositorio")
@click.option("--image", "-i", multiple=True, type=click.Path(exists=True),
              help="Imagen(es) para análisis (carga al iniciar la sesión)")
def chat(model: str, repo: str, image: tuple[str]):
    """Modo conversacional multi-turn con KC-RAG y persistencia."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax as RichSyntax
    console = Console(highlight=False, color_system="truecolor")
    _setup_signals()

    from leo_code.session import SessionManager
    sm = SessionManager()
    repo_abs = str(Path(repo).resolve())
    sid = sm.create_session(repo_abs, model).id
    pending_images = list(image) if image else []

    console.print(Panel.fit(
        f"[bold bright_blue]leo-code[/] v{VERSION}\n"
        f"repo: {repo_abs}\n"
        f"modelo: {model}\n"
        f"sesión: {sid[:12]}...\n"
        + (f"imágenes: {len(pending_images)}\n" if pending_images else "") +
        f"\n[dim]Comandos: /help  /model  /diff  /clear  /session  /exit  /image[/dim]",
        border_style="bright_blue",
        padding=(1, 3),
    ))

    state = {"model": model, "repo": repo_abs, "images": pending_images}
    total_saved_ref = [0]
    goal_state: dict = {}  # {"active": True, "runner": GoalRunner, "goal": Goal}

    # Init plugins + skills
    from leo_code.rag.agent.tools import ToolRegistry
    plugins_registry = ToolRegistry()
    from leo_code.plugins import PluginManager
    pm = PluginManager(repo_path=repo_abs)
    plugin_infos = pm.init(registry=plugins_registry)
    active_plugins = [p.name for p in plugin_infos if p.running] if plugin_infos else []

    from leo_code.skills import SkillManager
    skill_mgr = SkillManager()
    skill_mgr.load_skills(repo_abs)
    active_skills = [s.name for s in skill_mgr.list_all()]

    # LeoStatus HUD
    from leo_code.tui.status import LeoStatus
    status = LeoStatus(console, repo_path=repo_abs, model=model,
                       plugins=active_plugins, skills=active_skills,
                       session_id=sid)
    console.print(f"[dim]  {status._line_header()}[/dim]")

    while True:
        user_input = _read_input()
        if user_input is None:
            continue

        cmd = user_input.strip()
        if not cmd:
            continue

        handled = _handle_command(cmd, state, sm, sid, console)
        if handled is not None:
            if handled == "exit":
                pm.shutdown()
                console.print(f"\n[dim]Sesión guardada: {sid}[/dim]")
                console.print(f"[dim]Total tokens ahorrados vs baseline: ~{total_saved_ref[0]}[/dim]")
                break
            continue

        _cancel.cancelled = False
        images = state.pop("images", [])
        status.start_query(cmd, task_type="")

        async def stream_chat():
            from leo_code.rag.agent.loop import AgentLoop
            from leo_code.rag.agent.tools import ToolRegistry
            merged = ToolRegistry()
            for name, fn in plugins_registry._tools.items():
                merged._tools[name] = fn
            merged._definitions = list(plugins_registry._definitions)
            agent = AgentLoop(tools=merged, max_iterations=12)
            agent.interrupt = False

            events = agent.stream_run(
                user_input, repo_path=repo, model=state["model"],
                session_id=sid, images=images if images else None,
                plugin_manager=pm, skill_manager=skill_mgr,
            )
            for event in _render_stream(console, events, status, total_saved_ref):
                if _cancel.cancelled:
                    agent.interrupt = True

        asyncio.run(stream_chat())
        status.idle()


def _read_input() -> str | None:
    """Multi-line input con prompt_toolkit si está disponible, fallback a input()."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style
        from prompt_toolkit.completion import Completer, Completion, PathCompleter
    except ImportError:
        return _read_multiline_basic()

    try:
        hist_path = Path(os.getenv("LEO_CACHE_DIR", "./cache")) / "leo_history"
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        session = PromptSession(history=FileHistory(str(hist_path)))

        style = Style.from_dict({"prompt": "ansicyan bold"})

        class LeoCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if text.startswith("/"):
                    for cmd in ["/help", "/model ", "/image ", "/diff", "/clear",
                                "/session", "/sessions", "/exit", "/quit"]:
                        if cmd.startswith(text):
                            yield Completion(cmd, start_position=-len(text))
                else:
                    word = text.split()[-1] if " " in text else text
                    if word and len(word) >= 1:
                        cwd = Path.cwd()
                        for p in sorted(cwd.iterdir()):
                            pname = p.name + ("/" if p.is_dir() else "")
                            if pname.startswith(word):
                                yield Completion(pname, start_position=-len(word))

        completer = LeoCompleter()
        lines = []
        prompt = [("class:prompt", "> ")]
        first = True
        while True:
            try:
                line = session.prompt(
                    prompt if first else [("class:prompt", ". ")],
                    style=style, completer=completer, multiline=False,
                ).rstrip()
            except (EOFError, KeyboardInterrupt):
                return None
            first = False
            if line.endswith("\\"):
                lines.append(line[:-1])
            elif line == "" and not lines:
                return None
            else:
                lines.append(line)
                return "\n".join(lines)
    except Exception:
        return _read_multiline_basic()


def _read_multiline_basic() -> str | None:
    lines = []
    prompt = "> "
    while True:
        try:
            line = input(prompt).rstrip()
        except (EOFError, KeyboardInterrupt):
            return None
        if line.endswith("\\"):
            lines.append(line[:-1])
            prompt = ". "
        elif line == "" and not lines:
            return None
        else:
            lines.append(line)
            return "\n".join(lines)


def _handle_command(cmd: str, state: dict, sm, sid: str, console) -> str | None:
    if cmd == "/help":
        console.print("""
[bold]Comandos:[/bold]
  /model <id>     Cambiar modelo (p.ej. /model deepseek/deepseek-v4-pro)
  /model list     Listar modelos disponibles
  /goal <tarea>   Modo goal: no para hasta completar la tarea
  /goal status    Ver progreso del goal actual
  /goal cancel    Cancelar goal activo
  /image <path>   Cargar imagen para análisis de visión
  /init           Generar .leo-code/config.json optimizado para este proyecto
  /doctor         Diagnóstico del sistema (providers, cache, índice)
  /cost           Ver costes de la sesión por modelo
  /compact        Compactar historial de la conversación
  /permissions    Configurar permisos de tools (auto/ask/deny)
  /diff           Ver git diff de los cambios hechos
  /clear          Limpiar pantalla
  /session        Info de la sesión actual
  /sessions       Listar sesiones guardadas
  /exit           Salir y guardar sesión
  \\\\               Continuar en la línea siguiente (multi-línea)
""")
        return ""

    if cmd.startswith("/image "):
        img_path = cmd.split("/image ", 1)[1].strip()
        if Path(img_path).exists():
            state.setdefault("images", []).append(img_path)
            console.print(f"[green]Imagen cargada: {img_path} ({len(state['images'])} en cola)[/green]")
        else:
            console.print(f"[red]No encontrada: {img_path}[/red]")
        return ""

    if cmd.startswith("/model "):
        arg = cmd.split("/model ", 1)[1].strip()
        if arg == "list":
            from leo_code.rag.llm import discover_providers, discover_models
            providers = discover_providers()
            console.print(f"\n[bold]Providers detectados:[/bold] {', '.join(providers)}")
            models = discover_models()
            for m in models[:20]:
                cost = f"${m.cost_input:.2f}/${m.cost_output:.2f} por 1M tokens"
                console.print(f"  [cyan]{m.id}[/cyan] — {m.name} [dim]({cost}, {m.tier})[/dim]")
            console.print()
        else:
            state["model"] = arg
            console.print(f"\n[green]Modelo: {arg}[/green]\n")
        return ""

    if cmd == "/diff":
        import subprocess
        try:
            from rich.syntax import Syntax
            r = subprocess.run("git diff", shell=True, cwd=state["repo"],
                               capture_output=True, text=True, timeout=10)
            out = r.stdout or "[sin cambios]"
            console.print(Syntax(out, "diff", theme="monokai", background_color="default"))
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        return ""

    if cmd == "/clear":
        console.clear()
        return ""

    if cmd == "/session":
        s = sm.get_session(sid)
        if s:
            console.print(f"\n  sesión: {s.id}\n  repo: {s.repo_path}\n  modelo: {s.model}")
            console.print(f"  mensajes: {s.message_count}\n  tokens: {s.total_tokens}\n  creada: {s.created_at}\n")
        else:
            console.print("[yellow]Sesión no encontrada[/yellow]")
        return ""

    if cmd == "/sessions":
        sessions = sm.list_sessions(10)
        console.print(f"\n[bold]Sesiones guardadas:[/bold] {len(sessions)}")
        for s in sessions:
            marker = " *" if s.id == sid else ""
            console.print(f"  [cyan]{s.id[:12]}[/cyan]{marker} — {s.repo_path} — {s.message_count} msgs\n")
        return ""

    if cmd in ("/exit", "/quit"):
        return "exit"

    if cmd.startswith("/goal"):
        return _handle_goal(cmd, state, console, sid, pm, skill_mgr, status)

    if cmd == "/init":
        return _handle_init(state, console)

    if cmd == "/doctor":
        return _handle_doctor(state, console)

    if cmd == "/cost":
        return _handle_cost(console, sm, sid)

    if cmd == "/compact":
        return _handle_compact(console)

    if cmd.startswith("/permissions"):
        return _handle_permissions(cmd, state, console)

    return None


@cli.command()
@click.argument("repo", default=".")
@click.option("--languages", "-l", default="auto",
              help="Lenguajes (auto, python, javascript, go, rust, java, ruby)")
@click.option("--verbose", "-v", is_flag=True, help="Mostrar progreso por archivo")
def index(repo: str, languages: str, verbose: bool):
    """Indexa un repositorio para KC-RAG."""
    from rich.console import Console
    console = Console()
    from leo_code.rag.indexer import Indexer
    langs = [l.strip() for l in languages.split(",")]

    console.print(f"[bold]Indexando[/bold] {Path(repo).resolve()}")
    console.print(f"Lenguajes: {', '.join(langs)}")
    indexer = Indexer()
    count = indexer.build(repo, languages=langs, verbose=verbose)
    console.print(f"[green]✓ Listo. {count} cápsulas indexadas.[/green]")


def _handle_goal(cmd: str, state: dict, console, sid: str,
                 pm, skill_mgr, status) -> str | None:
    if cmd == "/goal status":
        if goal_state.get("goal"):
            g = goal_state["goal"]
            done = sum(1 for s in g.steps if s.status == "done")
            console.print(f"\n[bold]Goal activo:[/bold] {g.description[:80]}")
            bar = "█" * done + "░" * (len(g.steps) - done) if g.steps else "sin pasos"
            console.print(f"  {bar} {done}/{len(g.steps)} pasos")
            console.print(f"  Estado: [cyan]{g.status}[/cyan] · {g.total_tokens} tok · {g.total_duration_ms}ms")
            console.print()
        else:
            console.print("[dim]Sin goal activo[/dim]")
        return ""

    if cmd == "/goal cancel":
        if goal_state.get("runner"):
            goal_state["runner"].cancel()
            console.print("[yellow]Goal cancelado[/yellow]")
            goal_state.clear()
        else:
            console.print("[dim]Sin goal activo[/dim]")
        return ""

    if cmd.startswith("/goal "):
        goal_text = cmd.split("/goal ", 1)[1].strip()
        if not goal_text:
            return ""

        _cancel.cancelled = False
        console.print(f"\n[bold bright_blue]🎯 Goal:[/bold bright_blue] {goal_text[:120]}\n")

        async def run_goal():
            from leo_code.rag.agent.loop import AgentLoop
            from leo_code.rag.agent.tools import ToolRegistry
            merged = ToolRegistry()
            for name, fn in plugins_registry._tools.items():
                merged._tools[name] = fn
            merged._definitions = list(plugins_registry._definitions)
            agent = AgentLoop(tools=merged, max_iterations=15)
            agent.interrupt = False

            async for event in agent.goal_stream_run(
                goal_text, repo_path=state["repo"], model=state["model"],
                plugin_manager=pm, skill_manager=skill_mgr,
            ):
                if _cancel.cancelled:
                    agent.interrupt = True
                etype = event["type"]

                if etype == "goal_start":
                    console.print(f"[dim]  id: {event['goal']}[/dim]")
                elif etype == "goal_phase":
                    prefix = {"planning": "🧠 Planeando...", "verifying": "🔍 Verificando..."}.get(event["phase"], "")
                    console.print(f"\n[bold]{prefix}[/bold]")
                elif etype == "plan":
                    steps = event.get("steps", [])
                    for i, s in enumerate(steps, 1):
                        console.print(f"  [dim]{i}.[/dim] {s}")
                    console.print()
                elif etype == "step_start":
                    console.print(f"  [cyan]┌─ Paso {event['step']}/{event['total']}[/cyan] — {event.get('description','')[:100]}")
                elif etype == "step_done":
                    icon = "✓" if event.get("status") == "done" else "✗"
                    color = "green" if event.get("status") == "done" else "red"
                    console.print(f"  [{color}]└─ {icon} {event['step']}/{event['progress']} · {event.get('tokens',0)} tok · {event.get('duration_ms',0)}ms[/{color}]")
                elif etype == "replan":
                    added = event.get("added_steps", [])
                    console.print(f"  [yellow]↻ Re-plan: +{len(added)} pasos alternativos[/yellow]")
                elif etype == "verify":
                    result = event.get("result", {})
                    console.print(f"  [dim]Verificacion: {result.get('result', '')[:200]}[/dim]")
                elif etype == "goal_done":
                    bar = "█" * event.get("steps_done", 0) + "░" * max(0, event.get("total_steps", 1) - event.get("steps_done", 0))
                    console.print(f"\n  {bar}")
                    color = "green" if event.get("status") == "done" else "yellow"
                    console.print(f"  [{color}]🎉 Goal {event['status']}: {event['steps_done']}/{event['total_steps']} pasos · {event['tokens']} tok · {event['duration_ms']}ms[/{color}]\n")
                    goal_state["goal"] = None  # clear on done
                elif etype == "goal_error":
                    console.print(f"[red]Error: {event['error']}[/red]")

        asyncio.run(run_goal())
        return ""

    return None


def _handle_init(state: dict, console) -> str | None:
    """Genera .leo-code/config.json optimizado para el proyecto."""
    repo = state["repo"]
    console.print(f"\n[bold]🔍 Analizando {Path(repo).name}...[/bold]\n")

    frameworks = set()
    caps_count = "?"
    try:
        cache_dir = Path(os.getenv("LEO_CACHE_DIR", "./cache"))
        idx_path = cache_dir / "kc_index.json.gz"
        if idx_path.exists():
            import gzip, json as _json
            data = _json.loads(gzip.decompress(idx_path.read_bytes()))
            caps_count = str(data.get("total_capsules", "?"))
            for cap_data in data.get("capsules", {}).values():
                fw = cap_data.get("properties", {}).get("framework", "")
                if fw:
                    frameworks.add(fw)
    except Exception:
        pass

    lang = "python"
    for f in Path(repo).iterdir():
        if f.name == "package.json":
            lang = "typescript"
        elif f.name == "go.mod":
            lang = "go"
        elif f.name == "Cargo.toml":
            lang = "rust"

    if frameworks:
        console.print(f"  [green]✓[/green] Frameworks: [cyan]{', '.join(sorted(frameworks))}[/cyan]")
    if caps_count != "?":
        console.print(f"  [green]✓[/green] {caps_count} cápsulas indexadas")

    config = {
        "plugins": {},
        "permissions": {"mode": "ask", "auto_allow": ["read_file", "list_files", "search_code", "git_diff"]},
    }
    if "fastapi" in frameworks or "flask" in frameworks:
        config["plugins"]["lsp"] = {"type": "builtin"}
        config["plugins"]["linter"] = {"type": "builtin"}
    if any(f in frameworks for f in ("react", "vue", "angular", "svelte")):
        config["plugins"]["lsp"] = {"type": "builtin"}
        config["plugins"]["linter"] = {"type": "builtin"}

    dest = Path(repo) / ".leo-code"
    dest.mkdir(parents=True, exist_ok=True)
    import json as _json
    (dest / "config.json").write_text(_json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n  [green]✓[/green] Config: [cyan].leo-code/config.json[/cyan]")
    console.print(f"  [dim]Ejecuta `leo-code chat` para empezar[/dim]\n")
    return ""


def _handle_doctor(state: dict, console) -> str | None:
    """Diagnóstico del sistema."""
    console.print(f"\n[bold]🔍 Diagnóstico leo-code v{VERSION}[/bold]\n")
    console.print(f"  [green]✓[/green] Python {sys.version.split()[0]}")

    try:
        cache_dir = Path(os.getenv("LEO_CACHE_DIR", "./cache"))
        idx_path = cache_dir / "kc_index.json.gz"
        if idx_path.exists():
            import gzip, json as _json
            data = _json.loads(gzip.decompress(idx_path.read_bytes()))
            total = data.get("total_capsules", 0)
            console.print(f"  [green]✓[/green] KC-RAG index: {total} cápsulas")
        else:
            console.print(f"  [yellow]⚠[/yellow] KC-RAG index: no encontrado. `leo-code index .`")
    except Exception:
        console.print(f"  [yellow]⚠[/yellow] KC-RAG index: error")

    try:
        from leo_code.core.cache import init, is_available
        init()
        console.print(f"  [green]✓[/green] Redis cache" if is_available() else f"  [dim]○[/dim] Redis cache: no disponible (opcional)")
    except Exception:
        console.print(f"  [dim]○[/dim] Redis cache: no configurado")

    from leo_code.rag.llm import discover_providers, CATALOG
    discovered = discover_providers()
    console.print(f"\n  [bold]Providers:[/bold]")
    for p in ["anthropic", "openai", "google", "mistral", "groq", "cohere", "openrouter", "together", "azure", "bedrock", "ollama"]:
        status = "[green]✓[/green]" if p in discovered else "[dim]○[/dim]"
        models = [m for m in CATALOG.values() if m.provider == p]
        cost_str = f"${models[0].cost_input:.2f}/{models[0].cost_output:.2f}" if models else "?"
        console.print(f"    {status} {p:<14} {cost_str} por 1M tok")
    console.print()
    return ""


def _handle_cost(console, sm, sid: str) -> str | None:
    """Muestra costes de la sesión."""
    s = sm.get_session(sid)
    if not s:
        console.print("[yellow]Sesión no encontrada[/yellow]")
        return ""
    from leo_code.rag.llm.catalog import estimate_cost
    tokens = s.total_tokens or 0
    cost = estimate_cost(s.model, tokens // 2, tokens // 2)
    console.print(f"\n[bold]💰 Costes[/bold]")
    console.print(f"  Modelo: [cyan]{s.model}[/cyan]")
    console.print(f"  Tokens: {tokens:,}")
    console.print(f"  Coste: [green]${cost:.4f}[/green]")
    console.print(f"  Ahorro: ~{max(0, s.message_count * 20000 - tokens):,} tok\n")
    return ""


def _handle_compact(console) -> str | None:
    """Compacta historial (placeholder)."""
    console.print("\n[bold]📦 Compactando...[/bold]")
    console.print("  [dim]La compactacion automatica se activa a los 30 mensajes[/dim]")
    console.print("  [dim]Usa /sessions para gestionar sesiones[/dim]\n")
    return ""


def _handle_permissions(cmd: str, state: dict, console) -> str | None:
    """Configura permisos de tools."""
    from leo_code.rag.agent.permissions import PermissionManager
    pm = PermissionManager(repo_path=state["repo"])
    if cmd == "/permissions":
        console.print(f"\n[bold]Permisos:[/bold] [cyan]{pm.mode}[/cyan]")
        console.print(f"  Auto-allow: {', '.join(pm.auto_allow) or 'ninguno'}")
        console.print(f"  Auto-deny: {', '.join(pm.auto_deny) or 'ninguno'}")
        console.print(f"\n  /permissions auto  — permitir todo")
        console.print(f"  /permissions ask   — preguntar (recomendado)")
        console.print(f"  /permissions deny  — rechazar todo\n")
    elif cmd == "/permissions auto":
        console.print("[green]Permisos: auto[/green]")
    elif cmd == "/permissions ask":
        console.print("[yellow]Permisos: ask[/yellow]")
    elif cmd == "/permissions deny":
        console.print("[red]Permisos: deny[/red]")
    return ""


if __name__ == "__main__":
    cli()
