"""kc-code CLI: agente de terminal para asistencia en programación.

Comandos:
    kc-code ask "refactor auth to async"    # Consulta al agente
    kc-code index .                          # Indexar repo
    kc-code watch .                          # Watch mode + index incremental
"""

import sys
import click
from pathlib import Path


@click.group()
@click.version_option(version="0.1.0", prog_name="kc-code")
def cli():
    """kc-code — terminal agent con retrieval estructural de código.

    Model-agnostic. MIT. Menos tokens, menos alucinaciones.
    """
    pass


@cli.command()
@click.argument("query")
@click.option("--model", "-m", default="anthropic/claude-sonnet-4",
              help="Modelo a usar (anthropic/claude-sonnet-4, openai/gpt-4o, ollama/qwen2.5-coder)")
@click.option("--repo", "-r", default=".", help="Ruta del repositorio")
def ask(query: str, model: str, repo: str):
    """Consulta al agente KC-Code."""
    click.echo(f"[kc-code] Consulta: {query}")
    click.echo(f"[kc-code] Modelo: {model}")
    click.echo(f"[kc-code] Repo: {Path(repo).resolve()}")

    # TODO: Integrar AgentLoop.run()
    click.echo("\n[AgentLoop.run() — pendiente de implementar]")
    click.echo("Próximamente: retrieval estructural → prompt comprimido → LLM → respuesta.")


@cli.command()
@click.argument("repo", default=".")
@click.option("--languages", "-l", default="python",
              help="Lenguajes a indexar (python, javascript, typescript, rust, go)")
@click.option("--tree-sitter", is_flag=True, help="Usar tree-sitter en vez de AST")
@click.option("--verbose", "-v", is_flag=True, help="Mostrar progreso por archivo")
@click.option("--save", "-s", default=None, help="Guardar índice a archivo JSON")
def index(repo: str, languages: str, tree_sitter: bool, verbose: bool, save: str):
    """Indexa un repositorio para KC-RAG."""
    from leo_code.rag.indexer import Indexer
    langs = [l.strip() for l in languages.split(",")]

    click.echo(f"[kc-code] Indexando {Path(repo).resolve()} ({', '.join(langs)})...")
    indexer = Indexer()
    count = indexer.build(repo, languages=langs, use_tree_sitter=tree_sitter, verbose=verbose)
    if save:
        indexer.save(save)
    click.echo(f"[kc-code] Listo. {count} cápsulas.")


@cli.command()
@click.argument("repo", default=".")
@click.option("--languages", "-l", default="python",
              help="Lenguajes a observar")
def watch(repo: str, languages: str):
    """Observa cambios en el repo y reindexa incrementalmente."""
    from leo_code.rag.indexer import Indexer
    langs = [l.strip() for l in languages.split(",")]

    indexer = Indexer()
    click.echo(f"[kc-code] Indexación inicial de {Path(repo).resolve()}...")
    count = indexer.build(repo, languages=langs)
    click.echo(f"[kc-code] {count} cápsulas indexadas. Modo watch activo.")

    indexer.watch(repo)


if __name__ == "__main__":
    cli()
