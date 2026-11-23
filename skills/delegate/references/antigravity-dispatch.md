# Antigravity Reviewer (Aga)

Aga (Agnieszka) runs a `review-changes` Reviewer pass on Google Antigravity's CLI, `agy`, with Gemini 4 Neon at high effort.

## Availability

Available when `agy models` lists `gemini-4-neon-high` (the effort is part of the model ID; `agy` rejects `--effort` for Neon) and the jail command below runs `/usr/bin/true` in place of `agy`. Otherwise tell the user that Aga was skipped and why.

## Isolation

`agy`'s own controls are not a boundary: user settings may auto-approve every tool, `--mode plan` restricts none, regex permission rules match unreliably, `--sandbox` is a silent no-op where the host lacks one, and `agy` runs hooks and plugins from any workspace `.agents/`, trusted or not. So she runs in a bubblewrap jail that sees only throwaway copies. Rebuild both directories for every launch:

- **Workspace** `<WS>` = `<SCRATCH_DIR>/agy-ws`: the committed, clean reviewed worktree exported into `<WS>/src/` with `git -C <WORKTREE> checkout-index -a --prefix=<WS>/src/` (unlike `git archive`, it ignores the PR's `export-ignore`; PR paths stay below `src/`, so its symlinks cannot redirect the writes below). Under `<WS>/.review/`: the diff (`git -C <WORKTREE> diff <BASE_REF>...HEAD --output=<WS>/.review/diff.patch`), the changed and tracked file lists, the PR title, body and CI status, the Context Digest, a copy of `<PLUGIN_ROOT>/skills`, and her brief. Create `<WS>/out/`. Last, remove rule, hook and link files: `find <WS> \( -name .agents -o -name .agent -o -name .gemini -o -name AGENTS.md -o -name GEMINI.md -o -type l \) -prune -exec rm -rf {} +`.
- **Home** `<AH>` = `<SCRATCH_DIR>/agy-home`: copies of `~/.gemini/antigravity-cli/{antigravity-oauth-token,bin,builtin}` and `~/.config/antigravity` only — not the user's settings, rules, skills or history.
- **Settings** `<SCRATCH_DIR>/agy-settings.json`:

  ```json
  {"toolPermission": "request-review", "allowNonWorkspaceAccess": false, "enableTerminalSandbox": false,
   "permissions": {"ask": [], "deny": [], "allow": ["write_file(<WS>/out/)",
     "command(grep)", "command(ls)", "command(cat)", "command(head)", "command(tail)", "command(wc)"]}}
  ```

  The jail replaces `agy`'s own terminal sandbox, which cannot start inside it and would fail every command. None of these runs other programs (unlike `find -exec` or `sort --compress-program`), which matters because the jail shares the host network. In headless mode any other action is denied and ends the run with no output (exit 2): a failed pass.

## Run

Her brief (`review-changes` full-review template, role `qa-agy`, paths inside `<WS>`) names the allowed commands as the only ones, forbids MCP and web tools and `gate` (the coordinator runs it), points her at `src/` and `.review/`, and asks for `out/qa-agy-findings.json` and `out/qa-agy-coverage.md`. In the background (foreground in headless hosts, with `--print-timeout` under the host's command time limit), `<HOME>` being the user's home:

```bash
bwrap --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --ro-bind /etc /etc --ro-bind <RESOLV_DIR> <RESOLV_DIR> --proc /proc --dev /dev --tmpfs /tmp --bind <AH> <HOME> --ro-bind <HOME>/.local/bin/agy <HOME>/.local/bin/agy --bind <WS> <WS> --ro-bind <SCRATCH_DIR>/agy-settings.json <SCRATCH_DIR>/agy-settings.json --chdir <WS> --unshare-all --share-net --die-with-parent --clearenv --setenv HOME <HOME> --setenv PATH /usr/bin:/bin <HOME>/.local/bin/agy -p "Read .review/brief.md and follow it." --model gemini-4-neon-high --settings <SCRATCH_DIR>/agy-settings.json --print-timeout 45m
```

`<RESOLV_DIR>` is the directory of `readlink -f /etc/resolv.conf` (drop that bind when it is under `/etc`); adjust the `agy` binary path to the host. Then run `gate` on her findings and consolidate them as `qa-agy:<WS>/out/qa-agy-findings.json`. A non-zero exit, a timeout, or a missing or gate-failing findings file means her pass did not complete: say so in the executive summary and consolidate without her. Delete `<AH>` after the run. Her read commands can reach her own `agy` token inside the jail, so check her output for it before anything is published.
