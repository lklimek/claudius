---
name: github
description: MUST use for all git/gh commands and GitHub interactions — PRs, issues, pushes, branches.
---

# GitHub Workflow

Prefer local `git` over `gh`. Use `gh` only for GitHub-specific operations (PRs, issues, releases, Actions). Full `gh` reference: <https://cli.github.com/manual/>

**Attribution**: Every PR, issue, and comment posted to GitHub **must** include this footer (blank line before it):

```
<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
```

## Committing

Stage specific files — never `git add .` or `git add -A`.

```bash
git add <file1> <file2>
git commit -m "$(cat <<'EOF'
<type>: <description>

<optional body>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`). Append `!` for breaking changes.

## Pushing

**Always ask the user for explicit confirmation before every push.** Never push automatically — even after committing or creating a PR. Even if the user agreed to push earlier, ask again before next push.

**Never force-push. Never amend commits.** Always create new commits. If force-push is required, ask the user to do it manually.

## Pull Requests

### Creating a PR

Check for a PR template first:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, read and fill it in. When applicable, include an informal user story (what the user can achieve, no technical details — start with "Imagine you are...").

Always create PRs as drafts:

```bash
gh pr create --draft --title "<type>: <description>" --body "$(cat <<'EOF'
## Issue being fixed or feature implemented

### User Story

### Details

Closes #<issue-number>

## What was done?

<description of changes>

## How has this been tested?

<testing details>

## Breaking Changes

None

## Checklist

- [x] I have performed a self-review of my own code
- [x] I have added or updated relevant tests
- [x] I have made corresponding changes to the documentation if needed

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
EOF
)"
```

### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft reviews.** The user must publish the review themselves.

**Always use wrapper scripts** (via `../../scripts/`) — they handle pagination, filtering, and input validation.

Create draft reviews by omitting the `"event"` field. `gh-post-review.sh` enforces this by stripping any `event` field:

```bash
cat > "$SESSION_DIR/pr-review.json" << 'ENDJSON'
{
  "commit_id": "<SHA>",
  "body": "Review summary.\n\n<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>",
  "comments": [
    {"path": "src/file.rs", "line": 42, "side": "RIGHT", "body": "Finding here."}
  ]
}
ENDJSON
../../scripts/gh-post-review.sh <owner> <repo> <number> "$SESSION_DIR/pr-review.json"
```

**Available scripts** (`../../scripts/`):

```
gh-fetch-review-comments.sh <owner> <repo> <pr>
  → {id, path, line, original_line, body, user, in_reply_to_id, html_url}

gh-fetch-reviews.sh <owner> <repo> <pr>
  → {id, state, submitted_at, body, user}

gh-post-review.sh <owner> <repo> <pr> <json_file>
  → Posts draft review. Input: {commit_id, body, comments: [{path, line, side, body}]}

gh-request-reviewer.sh <owner> <repo> <pr> <reviewer>

gh-list-review-threads.sh <owner> <repo> <pr>
  → {id, isResolved, comments: [{databaseId, path, body}]}

gh-resolve-review-thread.sh <thread_id>
  → Ask user before resolving. Never resolve partially addressed threads.

gh-pr-base-sha.sh <owner> <repo> <pr>
  → Base commit SHA.

diff-anchors.py <file_path> [...]
  → "path → sha256". For diff URLs: ...files#diff-<SHA256>R<line>

ghsu.py [--org ORG] <cmd> | --setup <org> | --verify [org] | --revoke [org] | --list
  → Per-org elevated token management. See "Elevated Permissions" section below.
```

For PR-level (non-diff) comments: `gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'`

### Issues

Check for issue templates (`git ls-tree HEAD --name-only -r .github/ | grep -i issue_template`) before creating. Always append attribution footer.

**Feature/enhancement issues must include a `### User Story` section** — an informal story describing what the user can achieve (no technical details). Start with "As a **\<persona\>**, I want to ... so that ...". Multiple personas are fine. Place user stories before technical details.

## Safety Rules

1. **Always ask before publishing anything to GitHub** — commits, pushes, PRs, issues, comments, reviews. Ask for confirmation before any state-changing action.
2. **Never force-push. Never amend commits.** Always create new commits. If force-push is needed, ask the user to do it manually.
3. **Never use `git add .` or `git add -A`** — stage specific files
4. **Never use interactive flags** (`-i`) — requires terminal input
5. **Never skip hooks** (`--no-verify`) unless explicitly requested
6. **Check for `.env`, credentials, or secret files** before staging — warn if found
7. **Check for PR/issue templates** before creating — use them if they exist
8. **Avoid `gh api`** — prefer high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand exists. Never use `gh api` for write operations — use wrapper scripts or `gh` subcommands instead.

## Escaping and Formatting

- Use HEREDOCs (`<<'EOF'`) for multi-line bodies
- When using `gh api` (read-only only), prefer `--jq` over `| jq` — `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion)

## Elevated Permissions (ghsu)

When a `gh` or `git` command fails with HTTP 403 (Forbidden) or "Resource not accessible", re-run it through ghsu to request elevated write permissions:

```bash
python3 ../../scripts/ghsu.py <original-command-and-args>
# Or with explicit org:
python3 ../../scripts/ghsu.py --org dashpay <original-command-and-args>
```

ghsu auto-detects the target org from `-R owner/repo` flags or the current repo's git remote. It shows a GUI popup (or terminal prompt) with the exact command and org, asking the user to approve. If approved, it re-executes the command with the org's stored read-write token.

- Exit code 4 → no token stored. Tell the user to run `python3 ../../scripts/ghsu.py --setup <org>` to configure their read-write PAT.
- Exit code 2 → user denied the request. Do not retry.
- Exit code 3 → no GUI and no terminal available. Inform the user.

## Troubleshooting

* `gh` command fails with "Projects (classic)" GraphQL error → `gh` version is outdated, upgrade needed.
