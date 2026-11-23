# Antigravity Reviewer (Aga)

Aga (Agnieszka) runs a `review-changes` Reviewer pass on Google Antigravity's CLI, `agy`, with Gemini 4 Neon at high effort.

## Availability

Available when `agy models` lists `gemini-4-neon-high` (the effort is part of the model ID; `agy` rejects `--effort` for Neon). When `agy` is installed but the command fails or the model is missing, tell the user that Aga was skipped and why.

## Isolation

User settings may auto-approve every tool, `--mode plan` restricts none, regex permission rules match unreliably, and `--sandbox` silently does nothing where the host lacks a sandbox. So Aga gets no shell commands and sees only a prepared workspace:

- **Workspace** `<WS>` = `<SCRATCH_DIR>/agy-ws`, outside any git checkout. Export the reviewed head with `git -C <WORKTREE> archive --format=tar --output=<SCRATCH_DIR>/agy-src.tar HEAD`, extract it into `<WS>` excluding `.agents` and `.gemini` (`agy` runs hooks and plugins found there, even in an untrusted folder or one added with `--add-dir`), then delete every symlink in `<WS>` (`find <WS> -type l -delete`).
- **Inputs** under `<WS>/.review/`: the diff (`git -C <WORKTREE> diff <BASE_REF>...HEAD --output=<WS>/.review/diff.patch`), the changed and tracked file lists, the PR title, body and CI status, the Context Digest, a copy of `<PLUGIN_ROOT>/skills`, and her brief. Create `<WS>/out/`.
- **Settings** `<SCRATCH_DIR>/agy-settings.json`, outside `<WS>`:

  ```json
  {"toolPermission": "request-review", "allowNonWorkspaceAccess": false, "enableTerminalSandbox": true,
   "permissions": {"ask": [], "deny": [], "allow": ["write_file(<WS>/out/)"]}}
  ```

  In headless mode every unlisted action is denied and ends the run with no output (exit 2): a failed pass, never a write.
- **No credentials** — unset the credential variables in the environment (`GH_TOKEN`, `GITHUB_TOKEN`, `SSH_AUTH_SOCK`, other service tokens) except `agy`'s own login.

## Run

Her brief (`review-changes` full-review template, role `qa-agy`, paths inside `<WS>`) says: read files with the file tool only, run no shell, MCP or web tools (any one ends the run), find code through `.review/` and the file lists, write `out/qa-agy-findings.json` and `out/qa-agy-coverage.md`. In the background:

```bash
env -C <WS> -u GH_TOKEN -u GITHUB_TOKEN -u SSH_AUTH_SOCK agy -p "Read .review/brief.md and follow it." --model gemini-4-neon-high --settings <SCRATCH_DIR>/agy-settings.json --sandbox --print-timeout 45m
```

`env -C` is GNU; elsewhere start `agy` from `<WS>`. A headless host runs it in the foreground with `--print-timeout` under the host's command time limit. Then run `gate` on her findings and consolidate them as `qa-agy:<WS>/out/qa-agy-findings.json`. A non-zero exit, a timeout, or a missing or gate-failing findings file means her pass did not complete: say so in the executive summary and consolidate without her.
