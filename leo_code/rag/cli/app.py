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


@click.group()
@click.version_option(version=VERSION, prog_name="leo-code")
def cli():
    """leo-code — terminal agent con KC-RAG estructural.

    Model-agnostic (12 providers). 11 lenguajes. 15x menos tokens.
    """
    pass


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

        async for event in agent.stream_run(
            query, repo_path=repo, model=model, use_kc_rag=not no_rag,
            images=list(image) if image else None,
        ):
            if _cancel.cancelled:
                agent.interrupt = True
                continue

            etype = event["type"]
            if etype == "context":
                console.print(f"  [dim italic]contexto KC-RAG · {event['tokens']} tokens · {event['task_type']}[/dim italic]\n")
            elif etype == "token":
                console.print(event["text"], end="", markup=False)
            elif etype == "tool_start":
                console.print(f"\n  [yellow]🔧 {event['name']}({event.get('args', {})})[/yellow]", highlight=False)
            elif etype == "tool_result":
                out = event.get("output", "")[:500]
                if out:
                    console.print(f"  [dim]{out}[/dim]")
            elif etype == "done":
                dur = event.get("duration_ms", 0)
                tokens = event.get("total_tokens", 0)
                saved = max(0, 20000 - tokens)
                console.print(f"\n  [dim]─── {event.get('iterations', 0)} iters · {tokens} tok · {dur}ms · ~{saved} tok ahorrados[/dim]")

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
    from rich.syntax import Syntax
    console = Console(highlight=False)
    _setup_signals()

    from leo_code.session import SessionManager
    sm = SessionManager()
    repo_abs = str(Path(repo).resolve())
    sid = sm.create_session(repo_abs, model).id
    pending_images = list(image) if image else []

    console.print(Panel.fit(
        f"[bold]leo-code[/bold] v{VERSION}\n"
        f"repo: {repo_abs}\n"
        f"modelo: {model}\n"
        f"sesión: {sid[:12]}...\n"
        + (f"imágenes: {len(pending_images)}\n" if pending_images else "") +
        f"\n[dim]Comandos: /help  /model  /diff  /clear  /session  /exit[/dim]\n"
        f"[dim]Multi-línea: termina con \\ para continuar[/dim]\n"
        f"[dim]/image <path> para cargar imagen durante la sesión[/dim]",
        border_style="blue",
        padding=(1, 3),
    ))

    state = {"model": model, "repo": repo_abs, "images": pending_images}
    total_saved = 0

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
    status.render()  # initial header

    console.print(f"[dim]  {status._line_header()}[/dim]")

    while True:
        user_input = _read_multiline(console)
        if user_input is None:
            continue

        cmd = user_input.strip()
        if not cmd:
            continue

        # Slash commands
        handled = _handle_command(cmd, state, sm, sid, console)
        if handled is not None:
            if handled == "exit":
                pm.shutdown()
                console.print(f"\n[dim]Sesión guardada: {sid}[/dim]")
                console.print(f"[dim]Total tokens ahorrados vs baseline: ~{total_saved}[/dim]")
                break
            continue

        _cancel.cancelled = False
        images = state.pop("images", [])  # consume once

        # Start LeoStatus for this query
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

            async for event in agent.stream_run(
                user_input, repo_path=repo, model=state["model"],
                session_id=sid, images=images if images else None,
                plugin_manager=pm, skill_manager=skill_mgr,
            ):
                if _cancel.cancelled:
                    agent.interrupt = True
                    continue

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
                    status.update_context(event.get("tokens", 0), event.get("task_type", ""))
                    console.print(f"[dim italic]  KC-RAG · {event['tokens']} tok · {event['task_type']}[/dim italic]")
                elif etype == "token":
                    console.print(event["text"], end="", markup=False)
                elif etype == "tool_start":
                    args_str = ", ".join(f"{k}={v}" for k, v in event.get("args", {}).items())
                    console.print(f"\n[yellow]  🔧 {event['name']}({args_str})[/yellow]", highlight=False)
                elif etype == "tool_result":
                    out = event.get("output", "")[:600]
                    if out:
                        if "diff" in event.get("name", ""):
                            console.print(Syntax(out, "diff", theme="monokai", background_color="default"))
                        else:
                            console.print(f"  [dim]{out}[/dim]")
                elif etype == "done":
                    dur = event.get("duration_ms", 0)
                    tokens = event.get("total_tokens", 0)
                    its = event.get("iterations", 0)
                    saved = max(0, 20000 - tokens)
                    status.end_query(tokens, its, dur, saved)
                    console.print(f"\n[dim]  {status._line_footer()}[/dim]\n")
                    nonlocal total_saved
                    total_saved += saved

        asyncio.run(stream_chat())
        status.idle()


def _read_multiline(console) -> str | None:
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
  /image <path>   Cargar imagen para análisis de visión (próxima query)
  /diff           Ver git diff de los cambios hechos
  /clear          Limpiar pantalla
  /session        Info de la sesión actual
  /sessions       Listar sesiones guardadas
  /exit           Salir y guardar sesión
  \\               Terminar línea con \\ para continuar en la siguiente
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
            r = subprocess.run("git diff", shell=True, cwd=state["repo"],
                               capture_output=True, text=True, timeout=10)
            out = r.stdout or "[sin cambios]"
            from rich.syntax import Syntax
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
            console.print(f"\n  sesión: {s.id}")
            console.print(f"  repo: {s.repo_path}")
            console.print(f"  modelo: {s.model}")
            console.print(f"  mensajes: {s.message_count}")
            console.print(f"  tokens: {s.total_tokens}")
            console.print(f"  creada: {s.created_at}\n")
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


if __name__ == "__main__":
    cli()
