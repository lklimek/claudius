# GitHub CLI Fallback

Use when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable — all GitHub API operations fall back to the `gh` CLI and wrapper scripts.

Full `gh` reference: <https://cli.github.com/manual/>

## Creating a PR

Check for a PR template first:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, fold its required content into the linked skeleton below. See the main skill's §Creating a PR for the rationale (plain language up top, technical detail in `Detailed discussion`).

Fill in the skeleton from [pr-body-template.md](pr-body-template.md) (fenced block only, not the page's title or prose), save the completed body to a file, then create the PR as a draft via `--body-file` (not `--body` — avoids shell-escaping the skeleton inline):

```bash
gh pr create --draft --title "<type>: <description>" --body-file /path/to/filled-in-pr-body.md
```

## Reviewing a PR

See [pr-review.md](pr-review.md) for the full procedure: fetching PR context, deduplication, diff verification, and posting draft reviews (MCP-first, CLI fallback).

## Using `gh api`

**Avoid `gh api`** — prefer high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand exists. Never use `gh api` for write operations — use wrapper scripts or `gh` subcommands instead.

Prefer `--jq` over `| jq` — `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion).

**`-f` vs `-F` footgun**: `-f key=value` ALWAYS sends a raw string, even when the value starts with `@` — it does NOT read the file. Only `-F key=@filename` (capital F) triggers type detection and reads the file. `-f body=@c1.md` silently posts the literal string `"@c1.md"`. To send a body from a file, always use `-F body=@file`.

## Issues

Check for issue templates before creating:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i issue_template
```

If none exists, fill in the skeleton from [issue-body-template.md](issue-body-template.md) (fenced block only; see the main skill's §Issues), save the completed body to a file, then:

```bash
gh issue create --title "<title>" --body-file /path/to/filled-in-issue-body.md
```

## Elevated Permissions (ghsudo) -- Optional Fallback

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
