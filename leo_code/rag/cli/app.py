"""leo-code CLI: agente de terminal para asistencia en programación.

Comandos:
    leo-code ask "refactor auth to async"    # Consulta al agente
    leo-code index .                          # Indexar repo
    leo-code chat                             # Modo conversacional multi-turn
"""

import os
import sys
import asyncio
import click
from pathlib import Path

VERSION = "0.2.0"


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
def ask(query: str, model: str, repo: str, no_rag: bool):
    """Consulta directa al agente con KC-RAG."""
    click.echo(f"[leo-code] Repo: {Path(repo).resolve()}")
    click.echo(f"[leo-code] Modelo: {model}")
    click.echo(f"[leo-code] KC-RAG: {'off' if no_rag else 'on'}")

    async def run():
        from leo_code.rag.agent.loop import AgentLoop
        agent = AgentLoop(max_iterations=12)
        result = await agent.run(query, repo_path=repo, model=model, use_kc_rag=not no_rag)
        click.echo(f"\n{result['respuesta']}")
        tokens = result.get("total_tokens", 0)
        dur = result.get("duration_ms", 0)
        saved = max(0, 20000 - tokens)
        click.echo(f"\n[{result['iterations']} iters, {tokens} tok, {dur}ms, ~{saved} tok ahorrados]")

    asyncio.run(run())


@cli.command()
@click.option("--model", "-m", default="deepseek/deepseek-v4-flash",
              help="Modelo LLM")
@click.option("--repo", "-r", default=".", help="Ruta del repositorio")
def chat(model: str, repo: str):
    """Modo conversacional multi-turn con persistencia."""
    from leo_code.session import SessionManager
    sm = SessionManager()
    repo_abs = str(Path(repo).resolve())
    sid = sm.create_session(repo_abs, model).id
    click.echo(f"[leo-code] Sesión: {sid[:12]}...")
    click.echo(f"[leo-code] Modelo: {model}  |  /exit para salir\n")

    while True:
        query = input("> ").strip()
        if query.lower() in ("/exit", "/quit", "exit", "quit"):
            click.echo(f"[leo-code] Sesión guardada: {sid}")
            break
        if not query:
            continue

        async def run_chat():
            from leo_code.rag.agent.loop import AgentLoop
            agent = AgentLoop(max_iterations=12)
            return await agent.run(query, repo_path=repo, model=model, session_id=sid)

        result = asyncio.run(run_chat())
        click.echo(f"\n{result['respuesta']}\n")


@cli.command()
@click.argument("repo", default=".")
@click.option("--languages", "-l", default="auto",
              help="Lenguajes (auto, python, javascript, go, rust, java, ruby)")
@click.option("--verbose", "-v", is_flag=True, help="Mostrar progreso por archivo")
def index(repo: str, languages: str, verbose: bool):
    """Indexa un repositorio para KC-RAG."""
    from leo_code.rag.indexer import Indexer
    langs = [l.strip() for l in languages.split(",")]

    click.echo(f"[leo-code] Indexando {Path(repo).resolve()} ({', '.join(langs)})...")
    indexer = Indexer()
    count = indexer.build(repo, languages=langs, verbose=verbose)
    click.echo(f"[leo-code] Listo. {count} cápsulas indexadas.")


if __name__ == "__main__":
    cli()
