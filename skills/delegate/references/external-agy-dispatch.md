# External Antigravity Launcher

Optional `agy` (Google Antigravity CLI) dispatch. Load through `delegate` only when `agy` is installed and an Antigravity worker is relevant. The worker is named Aga (Agnieszka).

## When to Enlist Aga

- **Opt-in**, or selected by the review rules (`review-changes` full mode adds her as a reviewer).
- **Available** when `agy models` lists `gemini-4-neon-high`; otherwise tell the user she was skipped and why.

## Model

`--model gemini-4-neon-high` (Gemini 4 Neon at high effort). The effort is part of the model ID; `agy` rejects `--effort` for Neon.

## Dispatch

Write the brief to a file (`delegate` § Agent Prompt Requirements) with absolute paths only — worktree, plugin skills, output files — and repository-scoped commands (`git -C <WORKTREE>`, `gh … -R <owner/repo>`): she does not start in the repository, so the brief overrides the producer contract's ban on `git -C`. Then, in the background:

```bash
env -C <CWD> agy -p "Read <BRIEF_FILE> and follow it." --model gemini-4-neon-high --print-timeout 45m
```

- **Working directory** `<CWD>`: `agy` runs hooks and rules from its working directory's `.agents/`. For work on a repository you do not control (reviews), create a new empty directory outside any git checkout (`mktemp -d` when the scratch directory sits in one); for implementation, use her pre-created worktree (`grand-admiral` § Worktree Isolation). `env -C` is GNU; elsewhere start `agy` from `<CWD>`.
- **Permissions**: she runs under the user's own `agy` settings, like Codex under Codex's. One action they would ask about ends a headless run with no output (exit 2).
- **Headless hosts** (no background jobs): run her in the foreground only when the host's command limit exceeds `--print-timeout`; otherwise skip her and say so.
- **Never push**: she commits and stops; the coordinator pushes.

## Result

A non-zero exit, a timeout, or missing output files mean the task did not complete: report it and continue without her. Her stdout holds her final reply; her files are the result.
