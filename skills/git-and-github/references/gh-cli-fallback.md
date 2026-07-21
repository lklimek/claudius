# GitHub CLI Fallback

Use this reference when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable. All GitHub API operations fall back to the `gh` CLI and wrapper scripts.

Full `gh` reference: <https://cli.github.com/manual/>

## Creating a PR

Check for a PR template first:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, read and fill it in, folding its required content into the skeleton below. See the main skill's §Creating a PR for the full rationale (plain language up top, technical detail in `Detailed discussion`).

Always create PRs as drafts:

```bash
gh pr create --draft --title "<type>: <description>" --body "$(cat <<'EOF'
**TL;DR:** <one plain-language sentence describing what this PR does>

## User story

As a **<role>**, I want to <what-to-do>, to achieve <user-goal>.

## Scenario

### Base flow

<the ordinary steps that lead to this situation — plain narrative>

### Actual behavior

<what happens today>

### Expected behavior

<what should happen instead>

## Detailed discussion

### What was done

<description of changes>

Closes #<issue-number>

### Testing

<testing details>

### Breaking changes

None

### Checklist

- [x] I have performed a self-review of my own code
- [x] I have added or updated relevant tests
- [x] I have made corresponding changes to the documentation if needed

### Attribution

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
EOF
)"
```

## Reviewing a PR

See [pr-review.md](pr-review.md) for the full procedure: fetching PR context, deduplication, diff verification, and posting draft reviews (MCP-first, CLI fallback).

## Using `gh api`

**Avoid `gh api`** -- prefer high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand exists. Never use `gh api` for write operations -- use wrapper scripts or `gh` subcommands instead.

When using `gh api`, prefer `--jq` over `| jq` -- `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion).

**`-f` vs `-F` footgun**: `-f key=value` ALWAYS sends a raw string, even when the value starts with `@` — it does NOT read the file. Only `-F key=@filename` (capital F) triggers type detection and reads the file. Using `-f body=@c1.md` silently posts the literal string `"@c1.md"` instead of the file's contents. To send a body from a file, always use `-F body=@file`.

## Issues

Check for issue templates before creating:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i issue_template
```

## Elevated Permissions (ghsudo) -- Optional Fallback

If you use a **read-only default token** with `gh`, install [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) for write operations. When a `gh` or `git` command fails with HTTP 403 (Forbidden), 404 (Not Found), or "Resource not accessible", re-run it through ghsudo. **Never fork the repository** — forking creates a separate repo and breaks push/PR workflows. GitHub may return 404 instead of 403 for private resources when the token lacks sufficient permissions.

```bash
ghsudo <original-command-and-args>
# Or with explicit org:
ghsudo --org dashpay <original-command-and-args>
```

```
ghsudo [--org ORG] <cmd> | --setup <org> | --verify [org] | --revoke [org] | --list
```

ghsudo auto-detects the target org from `-R owner/repo` flags or the current repo's git remote. It shows a GUI popup (or terminal prompt) with the exact command and org, asking the user to approve. If approved, it re-executes the command with the org's stored read-write token.

- Exit code 4 -> no token stored. Tell the user to run `ghsudo --setup <org>` to configure their read-write PAT.
- Exit code 2 -> user denied the request. Do not retry.
- Exit code 3 -> no GUI and no terminal available. Inform the user.

## Troubleshooting

* `gh` fails with network/connection errors -> sandbox is blocking `api.github.com`. Fix: add `"api.github.com"` to `sandbox.network.allowedDomains` in `settings.json`. Fallback: use `dangerouslyDisableSandbox: true` on the Bash tool call.
* `gh` command fails with "Projects (classic)" GraphQL error -> `gh` version is outdated, upgrade needed.
