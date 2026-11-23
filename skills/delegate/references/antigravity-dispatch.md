# Antigravity Reviewer (Aga)

Aga (Agnieszka) runs a `review-changes` Reviewer pass on Google Antigravity's CLI, `agy`, with Gemini 4 Neon at high effort.

## Availability

Available when `agy models` lists `gemini-4-neon-high` (the effort is part of the model ID; `agy` rejects `--effort` for Neon). When `agy` is installed but the command fails or the model is missing, tell the user that Aga was skipped and why.

## Isolation

`--mode plan` only prefixes the prompt and the user's own settings may auto-approve every tool, so enforce read-only with a session settings file. In headless mode every action outside its allow list is denied, and one denial ends the run with no output (exit 2), which counts as a failed pass, never as a write.

- **Settings** — `<SCRATCH_DIR>/agy-settings.json`, absolute paths resolved:

  ```json
  {"toolPermission": "request-review", "allowNonWorkspaceAccess": true, "enableTerminalSandbox": true,
   "permissions": {"ask": [], "deny": [], "allow": [
     "read_file(<WORKTREE>)", "read_file(<PLUGIN_ROOT>)", "read_file(<SCRATCH_DIR>)",
     "write_file(<SCRATCH_DIR>/agy)",
     "command(git -C <WORKTREE> log)", "command(git -C <WORKTREE> diff)", "command(git -C <WORKTREE> show)",
     "command(python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py gate)"]}}
  ```

- **Working directory** — an empty directory outside every workspace `agy` trusts (`<SCRATCH_DIR>/agy-cwd`): started inside the reviewed worktree, `agy` loads its hooks, rules and plugins.
- **No credentials** — unset the credential variables in the environment (`GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, service API keys). Aga has no `gh`: save what she needs from GitHub (PR body, CI status) under `<SCRATCH_DIR>` first.

## Run

Write her producer prompt (`review-changes` full-review template; role `qa-agy`; outputs under `<SCRATCH_DIR>/agy/`) to `<SCRATCH_DIR>/qa-agy-brief.md`, naming the allowed commands as the only ones she may run and telling her to read files with her file tool. Then, in the background (foreground in headless hosts):

```bash
env -C <SCRATCH_DIR>/agy-cwd -u GH_TOKEN -u GITHUB_TOKEN -u SSH_AUTH_SOCK agy -p "Read <SCRATCH_DIR>/qa-agy-brief.md and follow it." --model gemini-4-neon-high --settings <SCRATCH_DIR>/agy-settings.json --sandbox --print-timeout 45m
```

A non-zero exit, a timeout, or a missing or gate-failing findings file means her pass did not complete: state that in the executive summary and consolidate without her.
