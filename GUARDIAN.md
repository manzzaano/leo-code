# guardian: what a change breaks, and what isn't tested

`python -m leo_code.core.guardian` uses the same call graph as leo-mcp to answer, before a
change ships, which symbols depend on what you touched and which of them have no test. It is
deterministic: no LLM, and every result is cited `file:line`.

For each changed symbol it reports:

- **Blast radius:** the transitive callers, i.e. what can break.
- **Across the HTTP boundary:** changing an endpoint flags the frontend components that call it,
  through the same `fetch('/api/x')` → route edges that `trace` uses.
- **Coverage:** which affected symbols are covered by a test and which are not.

## CLI

```bash
# before editing: what depends on this symbol?
python -m leo_code.core.guardian -s compress

# on a PR: check the diff against main; exits non-zero if affected code has no test
python -m leo_code.core.guardian --base main

# pre-commit: only what's staged
python -m leo_code.core.guardian --staged
```

Example output:

```
changing `get_report`  [✗ NO test]
  → affects 3 symbol(s), 2 with NO test (risk)
    · Dashboard (component) @ web/app.tsx:14   [✗ NO test]
    · render_page (function) @ views.py:88     [✓ tested]
guardian · 1 changed · 3 affected · 2 with NO test (risk) — deterministic, with proof, zero LLM
```

## GitHub Action

`.github/workflows/guardian.yml` runs it on every pull request: it indexes the repo, checks the
diff against the base branch and fails the check when the change reaches code with no test,
with the details in the log.

## pre-commit

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: leo-guardian
      name: guardian (blast radius + coverage)
      entry: python -m leo_code.core.guardian --staged
      language: system
      pass_filenames: false
```

## From your coding agent

The MCP server exposes the same check as `graph` with `op=guard`: the agent calls
`graph(op="guard", symbol="<symbol>")` and gets the blast radius and coverage before it edits.

In Claude Code, `leo-mcp init` also installs a pre-edit hook that runs this check on its own and
warns, in one line, only when an edit reaches dependents with no test. See
[the README](README.md#it-warns-you-before-your-agent-breaks-something).

Like the rest of leo-mcp, it works on a static graph: dependencies through queues, WebSockets,
subprocesses or names built from strings are not in it.
