# GitHub CLI

All GitHub API operations use the `gh` CLI and the wrapper scripts at `<plugin-root>/scripts/`.

Full `gh` reference: <https://cli.github.com/manual/>

## Creating a PR

Check for a PR template first:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, fold its required content into the linked skeleton below. See the main skill's §Creating a PR for the rationale (plain language up top, technical detail in `Detailed discussion`).

Fill in the PR-body skeleton (`git-and-github` § Creating a PR links it; fenced block only, not the page's title or prose), save the completed body to a file, then create the PR as a draft via `--body-file` (not `--body` — avoids shell-escaping the skeleton inline):

```bash
gh pr create --draft --title "<type>: <description>" --body-file /path/to/filled-in-pr-body.md
```

## Reviewing a PR

The full procedure (fetching PR context, deduplication, diff verification, posting draft reviews) is the PR-review reference that `git-and-github` § Reviewing a PR links.

## Using `gh api`

**Avoid `gh api`** — prefer high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand exists. Never use `gh api` for write operations — use wrapper scripts or `gh` subcommands instead.

Prefer `--jq` over `| jq` — `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion).

**`-f` vs `-F` footgun**: `-f key=value` ALWAYS sends a raw string, even when the value starts with `@` — it does NOT read the file. Only `-F key=@filename` (capital F) triggers type detection and reads the file. `-f body=@c1.md` silently posts the literal string `"@c1.md"`. To send a body from a file, always use `-F body=@file`.

## Issues

Check for issue templates before creating:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i issue_template
```

If none exists, fill in the issue-body skeleton (fenced block only; `git-and-github` § Issues links it), save the completed body to a file, then:

```bash
gh issue create --title "<title>" --body-file /path/to/filled-in-issue-body.md
```

## PR waiter (`pr_watch.py`)

`python3 <plugin-root>/scripts/pr_watch.py` — `--repo owner/name` (or `REPO`) outside a checkout, `--help` for all options:

- `gate --gate-bot <login> [--gate-marker <text>] [--gate-feed-url <url>] <pr>` — push check for a bot that edits one status comment in place (default marker `<login>-gate`; optional JSON feed of its running reviews). A comment matching `--gate-busy` always holds; a feed ACTIVE entry holds unless the comment was edited later. Exit 3 = reviewing, hold the push; 0 = not, but `gate: none` (wrong login/marker?) or `feed: unavailable` means that source was not checked; 2 = comments fetch failure or bad usage, do not push blind. `GATE_BOT` / `GATE_MARKER` / `GATE_FEED_URL` set the defaults.
- `watch [--quiet-init] [--oneshot] [--ignore-pending] [--checks <regex>] [--gate-bot <login> [--gate-marker <text>]] <pr> [<pr> ...]` — polls every `--interval` (120 s) and prints one line per PR whose reading changed (state, review decision, unresolved threads, non-passing checks, `pr-hygiene` body block, gate line); `--oneshot` exits 0 after the first printing pass, or 2 after 5 passes in which every fetch failed; failed fetches (on stderr, once per outage) and a Hygiene block older than the head are skipped. Run it with `run_in_background` and `--quiet-init --oneshot`, re-read the PR state right before relaunching after each event (`--quiet-init` takes the relaunch reading as the new baseline); set `--checks` to the required checks so flapping auxiliary ones do not wake it.

## Elevated Permissions (ghsudo) -- Optional

If using a **read-only default token** with `gh`, install [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) for write operations. When a `gh` or `git` command fails with HTTP 403 (Forbidden), 404 (Not Found), or "Resource not accessible", re-run it through ghsudo. **Never fork the repository** — forking creates a separate repo and breaks push/PR workflows. GitHub may return 404 instead of 403 for private resources when the token lacks permissions.

```bash
ghsudo <original-command-and-args>
# Or with explicit org:
ghsudo --org dashpay <original-command-and-args>
```

```
ghsudo [--org ORG] <cmd> | --setup <org> | --verify [org] | --revoke [org] | --list
```

ghsudo auto-detects the target org from `-R owner/repo` flags or the current repo's git remote, then shows a GUI popup (or terminal prompt) with the exact command and org for user approval. If approved, it re-executes the command with the org's stored read-write token.

- Exit code 4 -> no token stored. Tell the user to run `ghsudo --setup <org>` to configure their read-write PAT.
- Exit code 2 -> user denied the request. Do not retry.
- Exit code 3 -> no GUI and no terminal available. Inform the user.

## Troubleshooting

* `gh` fails with network/connection errors -> sandbox is blocking `api.github.com`. Fix: add `"api.github.com"` to `sandbox.network.allowedDomains` in `settings.json`. Fallback: `dangerouslyDisableSandbox: true` on the Bash tool call.
* `gh` fails with "Projects (classic)" GraphQL error -> `gh` version is outdated, upgrade needed.
