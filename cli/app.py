"""leo-code CLI — agente de terminal con KC-RAG.

Comandos:
  leo-code ask  <query>   — consulta directa (una sola vuelta)
  leo-code chat           — modo conversacional multi-turn
  leo-code index <repo>   — indexar repositorio en KC-RAG
  leo-code serve          — arrancar el sidecar KC-RAG manualmente
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown

# Añadir kc-rag y kc-core al sys.path (monorepo: cli/ está en leo-code/)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "kc-rag"))
sys.path.insert(0, str(_ROOT / "kc-core"))

console = Console()

DEFAULT_MODEL = "deepseek/deepseek-chat"


def _ensure_sidecar():
    """Arrancar el sidecar KC-RAG si no está corriendo."""
    import httpx
    import subprocess

    try:
        httpx.get("http://localhost:9898/health", timeout=2)
        return
    except Exception:
        pass

    sidecar_dir = _ROOT / "sidecar"
    pythonpath = os.pathsep.join([
        str(sidecar_dir),
        str(_ROOT / "kc-rag"),
        str(_ROOT / "kc-core"),
    ])
    env = {**os.environ, "PYTHONPATH": pythonpath}
    subprocess.Popen(
        [sys.executable, "-m", "leo_mcp.server"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    console.print("[dim]Arrancando sidecar KC-RAG...[/dim]")
    time.sleep(4)


def _resolve_model(model: str) -> str:
    if model != "auto":
        return model
    try:
        from kc_code.llm.routing import route, classify_complexity
        from kc_code.llm.discovery import discover_providers
        providers = discover_providers()
        return route("medium", providers)
    except Exception:
        return DEFAULT_MODEL


def _run_agent(query: str, repo: str, model: str, use_kc_rag: bool,
               history: list | None = None) -> dict:
    from kc_code.agent.loop import AgentLoop
    loop = AgentLoop()
    return asyncio.run(loop.run(
        query=query,
        repo_path=os.path.abspath(repo),
        model=model,
        use_kc_rag=use_kc_rag,
        history=history,
    ))


@click.group()
def cli():
    """leo-code — agente de terminal con KC-RAG."""
    pass


@cli.command()
@click.argument("query")
@click.option("--repo", "-r", default=".", show_default=True, help="Ruta del repositorio")
@click.option("--model", "-m", default="auto", show_default=True,
              help="Modelo (auto|deepseek/deepseek-chat|anthropic/claude-sonnet-4|…)")
@click.option("--no-rag", is_flag=True, help="Desactivar contexto KC-RAG")
def ask(query: str, repo: str, model: str, no_rag: bool):
    """Consulta directa al agente."""
    m = _resolve_model(model)
    console.print(f"[dim]modelo: {m} | repo: {os.path.abspath(repo)}[/dim]\n")

    result = _run_agent(query, repo, m, not no_rag)

    console.print(Markdown(result["respuesta"] or ""))
    console.print(
        f"\n[dim]tokens: {result['total_tokens']} | "
        f"iteraciones: {result['iterations']}[/dim]"
    )


@cli.command()
@click.option("--repo", "-r", default=".", show_default=True, help="Ruta del repositorio")
@click.option("--model", "-m", default="auto", show_default=True,
              help="Modelo (auto|deepseek/deepseek-chat|anthropic/claude-sonnet-4|…)")
@click.option("--no-rag", is_flag=True, help="Desactivar contexto KC-RAG")
def chat(repo: str, model: str, no_rag: bool):
    """Modo conversacional multi-turn."""
    m = _resolve_model(model)
    repo_path = os.path.abspath(repo)
    history: list[dict] = []

    console.print(
        f"[bold blue]leo-code[/bold blue] [dim]chat — "
        f"modelo: {m} | repo: {repo_path}[/dim]\n"
        "[dim]Escribe 'exit' para salir[/dim]\n"
    )

    while True:
        try:
            query = console.input("[bold cyan]>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Saliendo.[/dim]")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q", "salir"):
            break

        result = _run_agent(query, repo_path, m, not no_rag, history=history)

        console.print()
        console.print(Markdown(result["respuesta"] or ""))
        console.print(
            f"[dim]tokens: {result['total_tokens']} | "
            f"iteraciones: {result['iterations']}[/dim]\n"
        )

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": result["respuesta"] or ""})


@cli.command()
@click.argument("repo", default=".")
@click.option("--languages", "-l", default="python,text", show_default=True,
              help="Lenguajes a indexar (csv)")
def index(repo: str, languages: str):
    """Indexar un repositorio en el sidecar KC-RAG."""
    _ensure_sidecar()
    import httpx

    repo_abs = os.path.abspath(repo)
    console.print(f"[dim]Indexando {repo_abs}…[/dim]")

    try:
        r = httpx.post(
            "http://localhost:9898/index",
            json={"repo_path": repo_abs, "languages": languages},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        console.print(
            f"[green]✓[/green] {data.get('capsules', 0)} cápsulas indexadas "
            f"en {data.get('repo', repo_abs)}"
        )
    except Exception as e:
        console.print(f"[red]Error al indexar:[/red] {e}")


@cli.command()
def serve():
    """Arrancar el sidecar KC-RAG en :9898."""
    sidecar_dir = _ROOT / "sidecar"
    pythonpath = os.pathsep.join([
        str(sidecar_dir),
        str(_ROOT / "kc-rag"),
        str(_ROOT / "kc-core"),
    ])
    env = {**os.environ, "PYTHONPATH": pythonpath}
    console.print("[dim]Arrancando leo-code-mcp en http://localhost:9898 …[/dim]")
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-m", "leo_mcp.server"],
        env=env,
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    cli()
