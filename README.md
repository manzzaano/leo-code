<div align="center">

# leo-mcp

**Give your coding agent the real call graph of your repo, with proof,**
**instead of letting it guess by grepping and reading whole files.**

[![Tests](https://github.com/manzzaano/leo-code/actions/workflows/test.yml/badge.svg)](https://github.com/manzzaano/leo-code/actions/workflows/test.yml)
[![Formal Audit](https://github.com/manzzaano/leo-code/actions/workflows/audit.yml/badge.svg)](https://github.com/manzzaano/leo-code/actions/workflows/audit.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![Protocol](https://img.shields.io/badge/protocol-MCP-6b4fbb)](https://modelcontextprotocol.io)

<table>
<tr>
<td align="center" width="220"><b>100%</b><br/><sub>call-graph precision and recall<br/>vs. Python's own <code>ast</code></sub></td>
<td align="center" width="220"><b>80–97%</b><br/><sub>fewer tokens per lookup<br/>vs. reading the files</sub></td>
<td align="center" width="220"><b>~6 s</b><br/><sub>from nothing to running,<br/>no API key, no GPU</sub></td>
</tr>
</table>

</div>

---

## Quickstart

```bash
npx -y leo-mcp doctor                       # one-time: fetches the engine and checks your setup
claude mcp add leo-mcp -- npx -y leo-mcp    # Claude Code (Windows: -- cmd /c npx -y leo-mcp)
```

Other clients: run `npx -y leo-mcp init --client opencode|cursor|codex` inside your project.

Requirements: Node ≥ 18 and [uv](https://docs.astral.sh/uv/) (uv fetches Python for you).
Without uv, the launcher uses a Python ≥ 3.11 on your PATH instead.
No API key: leo-mcp never calls an LLM. It parses your repo locally.

## What your agent gets

Two tools, plus server instructions that tell the agent when to use them.

**`graph`** gives deterministic answers from the parsed call graph, each one cited `file:line`:

```
> graph op=who_calls symbol=get_session
[who_calls] get_session — 10 result(s), with proof:
  · execute_batch (method) @ src/agents/executor_agent.py:32
  · _persist_jobs_sync (function) @ main.py:42
  · analyze_and_report (method) @ src/agents/advisor_agent.py:38
  · jobs (endpoint) @ src/api/app.py:94
  ...
```

| op | answers |
|---|---|
| `where` | where a symbol is defined |
| `who_calls` | its direct callers |
| `impact` | everything that transitively depends on it: what breaks if you change it |
| `trace` | the call path from A to B, including frontend `fetch('/api/x')` → backend route |
| `guard` | `impact` plus which affected symbols have **no test** |

**`get_context`** takes a question in plain language and returns the AST subgraph that answers it: the relevant symbols with their bodies, compressed. Every response says what it saved:

```
[leo-mcp · 1,381 tokens of code context · the 6 source files it draws from are ~7,891 tokens (-82%) · 476 symbols indexed]
```

## CLI

```bash
npx -y leo-mcp index        # index the current repo and show what leo-mcp sees
npx -y leo-mcp doctor       # check the install, print the config snippet
npx -y leo-mcp init         # add leo-mcp to this project's .mcp.json (never overwrites other servers)
```

```
leo-mcp indexed C:\...\NEXUS  (build in 0.17s)
  476 symbols in 35 files
    python           450
    typescript        25
  most depended-on (run graph op=guard before touching these):
    click                             11 callers  src/automation/human_behavior.py:37
    get_session                       10 callers  src/database/db_session.py:26
```

## Languages, and what it doesn't do

- **Full AST:** Python (`ast`) and TypeScript/TSX/JavaScript (tree-sitter), including functions declared as variables or object properties (`const Page = () => …`, `const load = useCallback(() => …)`, `api = { jobs: () => get("/api/jobs") }`) and Python class attributes (`min_match_score: int = 60`).
- **Approximate** (regex-level): Go, Java, Rust, C/C++, C#, Ruby, PHP, Kotlin, Swift and others.
- **Skipped:** dependencies, build output (`node_modules`, `.next`, `dist`, `target`…), minified bundles, files over 512 KB, and anything in `.gitignore` when the repo uses git.
- **Not in the graph:** it is a static graph. Calls through WebSockets, subprocesses, queues, reflection or string-built dispatch are not edges, and using a type (a dataclass in an annotation) is not a call. Values that merely come out of a call (`const rows = items.filter(…)`) are not symbols.
- **Your files stay put.** The index lives in your user cache (`%LOCALAPPDATA%\leo-mcp` or `~/.cache/leo-mcp`), never inside your repo. It is kept up to date incrementally as files change.

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `LEO_REPO` | client's working dir | repo to index when a tool call gives no `repo_path` |
| `LEO_SEMANTIC` | off | `1` with npx installs `leo-mcp[semantic]` (sentence-transformers, ~2 GB with torch) for semantic recall in `get_context`; `graph` doesn't need it |
| `LEO_CACHE_DIR` | user cache | where indexes and logs go |
| `LEO_MAX_FILE_KB` | `512` | skip source files larger than this |
| `LEO_MCP_FROM` | PyPI `leo-mcp==<version>` | install source for the npm launcher (local wheel, git URL) |

Python users can skip npm: `uvx leo-mcp`, or `pip install leo-mcp` and then `leo-mcp`.

---

## The guarantee: structural correctness, proven

`graph` doesn't estimate structure. It walks the parsed graph, and CI checks that graph against parsers that are not leo's. `benchmark/audit_formal.py` re-derives every edge with Python's `ast` and the TypeScript compiler `tsc`, compares edge by edge, and a regression can't merge (`.github/workflows/audit.yml`).

Last green CI run (`FORMAL: 5/5 → IRREFUTABLE`):

| Check | Scale | Measured |
|---|---|---|
| (a) Python graph vs `ast` | leo-code + 3 external repos (~100,400 symbols, ~480,200 edges) | **100.000% precision · 100.000% recall** |
| (a-ts) TS/JS graph vs `tsc` | TypeScript compiler repo (36,739 symbols) | **99.950% precision · 99.926% recall** (31 false / 46 missed of 62.2k edges) |
| (b) guardian coverage vs `coverage.py` | 146 executed functions | **0 false** in either direction |
| (c) blast radius vs real mutation testing | mutated `classify_task`, `get_budget` | every failing test **⊆** predicted |
| (d) latency at scale | 271,493 indexed symbols | worst query **1.98 ms** · guardian **13 ms** |

The TS/JS figure is left unrounded.

## Measured with real agents

**opencode, 15 tasks × 3 runs, full token accounting including subagents** (2026-07-14):

| Metric | Threshold | Result |
|---|---|---|
| Answer quality (LLM judge) | with MCP ≥ without | ✅ +0.18 (5.00 vs 4.82) |
| Duration | ≤ +10% | ✅ −14.2% |
| End-to-end tokens | ≤ +10% median per task | ✅ +1.9% median · **−30.1% pooled** |

The honest claim: savings are per lookup and show up on heavy tasks (pooled −30%). On a typical task the token cost is neutral. What an agent without it can't get is a structurally correct answer. An early "−40% end-to-end" goal was dropped after six configurations measured worse or neutral.

**Field test on a project that isn't this one** (2026-09-15, NEXUS: FastAPI + Next.js/TSX, not a git repo, with 49 MB of saved web pages inside):

| | Result |
|---|---|
| Install from scratch (`uvx`, cold cache) | 6 s, 114 MB, no torch |
| Indexed | 476 symbols (Python 450 · TypeScript 25); 59 of 60 minified bundles skipped |
| Index time | cold 1.0 s · reload from cache 0.05 s (CLI) |
| `graph` latency | < 10 ms |
| `get_context` vs reading the files it covers | −82% and −90% on the two sample questions |
| Files written inside the project | 0 (directory listing diffed before/after) |

Then real agents answered 8 questions about NEXUS whose answers are known, each with and without leo-mcp (read-only, n=1 per question):

| | Claude Code + Sonnet | opencode + DeepSeek V4 Flash |
|---|---|---|
| Tokens, median per task | **−21%** | −4% |
| Tokens, pooled | **−26%** | **−19%** |
| Duration | +0.4% | −2.2% |
| Questions where the agent used leo-mcp | 8/8 | 6/8 |
| Correct answers (without → with) | 7/8 → 7/8 | 7/8 → 7/8 |

Savings came from structural questions (impact of changing a type −59%, "what happens when I press Start" −69%). Simple lookups cost the same or more. With n=1 per question, treat per-task numbers as noisy.

The field test found and fixed several bugs a user would have hit: TS/TSX was never indexed through MCP, two first-use hangs on Windows (a `git` call and a native import, both blocked by the stdio pipe), a Python `d.get()` counted as a caller of a TypeScript `get()`, `who_calls` cited the caller's definition line instead of the call line, and asking about an HTTP endpoint returned its signature without the body.

---

## How it works

```
source ─► AST (Python ast, tree-sitter) ─► capsules: functions/classes with calls, file:line
        ─► per-repo index in the user cache, updated incrementally
        ─► graph: where / who_calls / impact / trace / guard     (no model involved)
        ─► get_context: exact + BM25 + structural scorer (+ semantic, optional) → RRF → compressed
```

Frontend/backend boundary: a `fetch('/api/users')` is stitched to the `@app.get('/api/users')` that serves it (`core/boundary.py`), so `trace` follows data across services. Edges never cross languages by name alone: a Python `d.get()` is not a caller of a TypeScript `get()`.

```
leo_code/
├── cli.py              # leo-mcp serve | index | doctor | init
├── engine.py           # per-repo persistent index + hybrid retrieval + compression
├── core/               # parsers, graphquery (the graph), guardian, boundary
├── rag/                # indexer, compressor, bm25, scorer, optional vector store
└── server/mcp_server.py
npm/                    # the `npx leo-mcp` launcher (runs the Python package via uv)
```

## Development

```bash
git clone https://github.com/manzzaano/leo-code.git && cd leo-code
pip install -e ".[dev]"
pytest -q                               # 154 tests, including an end-to-end stdio server test
node --test npm/bin/leo-mcp.test.js     # launcher
python benchmark/mcp_client_bench.py    # real MCP client, token-reduction gate
```

---

## En español

`leo-mcp` es un servidor MCP que le da a tu agente de código (Claude Code, opencode, Cursor, Codex) el grafo de llamadas real de tu repo. Con él responde dónde se define algo, quién lo llama, qué se rompe si lo cambias y el camino de A a B, citando siempre `archivo:línea`. Sin LLM y sin API key.

```bash
npx -y leo-mcp doctor
claude mcp add leo-mcp -- npx -y leo-mcp      # en Windows: -- cmd /c npx -y leo-mcp
```

Requisitos: Node ≥ 18 y [uv](https://docs.astral.sh/uv/), o Python ≥ 3.11. El índice vive en la caché de usuario, nunca dentro de tu proyecto. Los números y la metodología están arriba, con los comandos para reproducirlos.
