"""leo-mcp — CLI del producto.

  leo-mcp [serve]            servidor MCP por stdio (lo que lanza el cliente MCP)
  leo-mcp index [repo]       indexa y enseña qué ve leo-mcp (lenguajes, símbolos más usados)
  leo-mcp doctor [repo]      comprueba la instalación y da el snippet de configuración
  leo-mcp init [--client X]  registra leo-mcp en la config MCP del proyecto

Salida al usuario en inglés. `serve` no escribe NADA en stdout (canal JSON-RPC).
"""

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from leo_code import __version__

CLIENTS = ("claude", "cursor", "opencode", "codex")


def _launch() -> list[str]:
    """Comando que el cliente MCP ejecutará. Windows necesita `cmd /c` para lanzar npx."""
    return (["cmd", "/c"] if os.name == "nt" else []) + ["npx", "-y", "leo-mcp"]


def _quiet_index(repo: str) -> dict | None:
    """ensure_structural con los print() del indexer desviados a stderr."""
    from leo_code import engine
    real, sys.stdout = sys.stdout, sys.stderr
    try:
        return engine.ensure_structural(repo)
    finally:
        sys.stdout = real


def cmd_serve(_args) -> int:
    from leo_code.server.mcp_server import run_stdio
    run_stdio()
    return 0


def cmd_index(args) -> int:
    from leo_code import engine
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2
    stats = _quiet_index(repo)
    caps = engine._repo_caps(engine._get_indexer(), repo)
    if not caps:
        print(f"No indexable source files found in {repo}.")
        return 1
    langs = stats["by_language"] if stats else {}
    how = f"{stats['action']} in {stats['seconds']}s" if stats else "already up to date"
    print(f"leo-mcp indexed {repo}  ({how})")
    print(f"  {len(caps):,} symbols in {len({c.file_path for c in caps}):,} files")
    for lang, n in langs.items():
        print(f"    {lang:<12}{n:>8,}")
    from leo_code.core.graphquery import GraphQuery
    gq = GraphQuery({c.id: c for c in caps})  # callers globales (called_by solo es intra-archivo tras build)
    n_callers = lambda c: len({x.name for x in gq._callers_of(c.name)})
    hubs = sorted((c for c in caps if c.type not in ("module", "file_header", "variable", "constant")),
                  key=n_callers, reverse=True)[:5]
    hubs = [c for c in hubs if n_callers(c)]
    if hubs:
        print("  most depended-on (run graph op=guard before touching these):")
        for c in hubs:
            rel = os.path.relpath(c.file_path, repo).replace("\\", "/")
            print(f"    {c.name:<32} {n_callers(c):>3} callers  {rel}:{c.start_line}")
    print(f"  index cache: {engine.repo_index_path(repo)}")
    return 0


def cmd_doctor(args) -> int:
    from importlib import metadata, util
    from leo_code import engine
    ok = True

    def row(name, good, detail):
        nonlocal ok
        ok = ok and good is not False
        mark = {True: "ok ", False: "ERR", None: "-  "}[good]
        print(f"  [{mark}] {name:<11} {detail}")

    print(f"leo-mcp {__version__} doctor")
    py_ok = sys.version_info >= (3, 11)
    row("python", py_ok, f"{platform.python_version()} ({sys.executable})")
    try:
        row("mcp", True, f"{metadata.version('mcp')}")
    except metadata.PackageNotFoundError:
        row("mcp", False, "not installed")
    try:
        from leo_code.core.parser_ts import _parser
        _parser("tsx")
        row("typescript", True, "tree-sitter AST parser (TS/TSX/JS)")
    except Exception as e:
        row("typescript", False, f"tree-sitter unavailable, falling back to regex: {e}")
    row("semantic", None, "on (sentence-transformers)" if engine.SEMANTIC
        else "off (optional: install leo-mcp[semantic] or set LEO_SEMANTIC=1 with npx)")
    row("cache", None, str(engine._CACHE_DIR))
    repo = os.path.abspath(args.repo)
    idx_path = engine.repo_index_path(repo)
    row("repo", None, f"{repo} - " + ("indexed" if idx_path.exists() else "not indexed yet (run: leo-mcp index)"))
    if util.find_spec("sentence_transformers") and not engine.SEMANTIC:
        row("note", None, "semantic packages installed but LEO_SEMANTIC=0")

    launch = " ".join(_launch())
    print("\nAdd leo-mcp to your agent:")
    print(f"  Claude Code   claude mcp add leo-mcp -- {launch}")
    print(f"  any client    leo-mcp init --client {{{','.join(CLIENTS)}}}")
    print("\n" + ("Ready." if ok else "Fix the ERR rows above."))
    return 0 if ok else 1


def cmd_init(args) -> int:
    root = Path(args.repo).resolve()
    launch = _launch()
    if args.client == "codex":
        print("Add this to ~/.codex/config.toml:\n")
        print("[mcp_servers.leo-mcp]")
        print(f'command = "{launch[0]}"')
        print("args = [" + ", ".join(f'"{a}"' for a in launch[1:]) + "]")
        return 0
    std = {"command": launch[0], "args": launch[1:]}
    target, key, entry = {
        "claude": (root / ".mcp.json", "mcpServers", std),
        "cursor": (root / ".cursor" / "mcp.json", "mcpServers", std),
        "opencode": (root / "opencode.json", "mcp", {"type": "local", "command": launch, "enabled": True}),
    }[args.client]
    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            # Nunca reescribir una config que no entendemos: se perderían otros servers.
            print(f"{target} is not valid JSON ({e}); not touching it. Add manually:\n"
                  + json.dumps({key: {"leo-mcp": entry}}, indent=2), file=sys.stderr)
            return 1
    servers = data.setdefault(key, {})
    if "leo-mcp" in servers:
        print(f"leo-mcp is already configured in {target}")
        return 0
    servers["leo-mcp"] = entry
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Added leo-mcp to {target}. Restart {args.client} to load it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="leo-mcp", description="Call graph + AST context for coding agents, over MCP.")
    ap.add_argument("--version", action="version", version=f"leo-mcp {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the MCP server on stdio (default)")
    for name, help_ in (("index", "index a repo and show what leo-mcp sees"),
                        ("doctor", "check the installation and print the config snippet")):
        sub.add_parser(name, help=help_).add_argument("repo", nargs="?", default=".")
    p = sub.add_parser("init", help="register leo-mcp in a project's MCP config")
    p.add_argument("--client", choices=CLIENTS, default="claude")
    p.add_argument("repo", nargs="?", default=".")
    args = ap.parse_args(argv)
    if args.cmd not in (None, "serve"):
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(errors="replace")  # consolas cp1252 de Windows
    handler = {"index": cmd_index, "doctor": cmd_doctor, "init": cmd_init}.get(args.cmd, cmd_serve)
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
