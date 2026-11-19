# External Claude Reviews

Use when Anthropic is selected by `delegate` § Review Providers and no eligible native route exists. Require an installed, authenticated Claude CLI or configured launcher with the needed model and permissions; do not install tooling or configure credentials. Check the installed CLI's help before using version-dependent flags.

## Read-only CLI route

Prepare a prompt file and an MCP config containing `{"mcpServers": {}}` in the review scratch directory. Supply the scope/head, diff and source paths, requirements, known authorship, relevant CI evidence, absolute role-skill paths and producer contract. Identify a leaf reviewer; prohibit peer dispatch and GitHub/production writes. Ask for a JSON object containing the producer `findings` array and `coverage` Markdown in its final response. Tools below permit source inspection; the coordinator supplies command/CI evidence and owns validation.

Run from the reviewed checkout, choosing an available strong model (e.g. `opus`) and high effort. Feed the prompt on stdin and capture stdout/stderr with the host's process tool; shell equivalent:

```bash
claude -p --no-session-persistence --model opus --effort high \
  --tools Read,Grep,Glob --allowedTools Read,Grep,Glob \
  --permission-mode dontAsk --strict-mcp-config \
  --mcp-config "<REVIEW_DIR>/empty-mcp.json" --output-format json \
  < "<REVIEW_DIR>/prompt.txt" \
  > "<REVIEW_DIR>/claude-output.json" 2> "<REVIEW_DIR>/claude.stderr"
```

This route has no Bash, Write, Edit, Agent or MCP tools. If required role capabilities are missing, use a configured launcher with appropriately scoped permissions or report incomplete coverage; never bypass permissions. A review requiring tests or other writes uses a separate isolated worktree per `grand-admiral`.

## Collect

Track the returned process/session ID and collect completion in the same turn, also in headless mode. Use bounded waits; inspect that process's stderr/status for failures. A successful CLI exit alone is insufficient: reject error results, malformed output, missing coverage, or a response that did not perform the assigned pass.

Parse the CLI JSON envelope's `result` into findings and coverage. The coordinator writes the assigned producer files, runs `consolidate_reports.py gate`, and records actual provider/model and reviewed scope. Report unavailable/failed routes through the provider policy; never count them as completed passes. Do not end with the reviewer still running.
