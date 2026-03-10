# GitHub CLI Fallback

Use this reference when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable. All GitHub API operations fall back to the `gh` CLI and wrapper scripts.

Full `gh` reference: <https://cli.github.com/manual/>

## Creating a PR

Check for a PR template first:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, read and fill it in. When applicable, include an informal user story (what the user can achieve, no technical details -- start with "Imagine you are...").

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

## PR-Level Comments

For PR-level (non-diff) comments:

```bash
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'
```

## Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft reviews.** The user must publish the review themselves.

**Always use wrapper scripts** (via `../../scripts/`) -- they handle pagination, filtering, and input validation.

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
../../scripts/gh-post-review.sh <owner/repo> <number> "$SESSION_DIR/pr-review.json"
```

## Wrapper Scripts

All scripts are located at `../../scripts/` relative to this skill.

```
gh-fetch-review-comments.sh <owner/repo> <pr>
  -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

gh-fetch-reviews.sh <owner/repo> <pr>
  -> {id, state, submitted_at, body, user}

gh-post-review.sh <owner/repo> <pr> <json_file>
  -> Posts draft review. Input: {commit_id, body, comments: [{path, line, side, body}]}

gh-request-reviewer.sh <owner/repo> <pr> <reviewer>

gh-list-review-threads.sh <owner/repo> <pr>
  -> {id, isResolved, comments: [{databaseId, path, body}]}

gh-resolve-review-threads.sh <thread_id> [thread_id ...]
  -> Resolves all given threads in a single API call. Ask user before resolving.

gh-pr-base-sha.sh <owner/repo> <pr>
  -> Base commit SHA.

diff-anchors.py <file_path> [...]
  -> "path -> sha256". For diff URLs: ...files#diff-<SHA256>R<line>
```

## Using `gh api`

**Avoid `gh api`** -- prefer high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand exists. Never use `gh api` for write operations -- use wrapper scripts or `gh` subcommands instead.

When using `gh api`, prefer `--jq` over `| jq` -- `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion).

## Issues

Check for issue templates before creating:

```bash
git ls-tree HEAD --name-only -r .github/ | grep -i issue_template
```

## Elevated Permissions (ghsudo) -- Optional Fallback

If you use a **read-only default token** with `gh`, install [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) for write operations. When a `gh` or `git` command fails with HTTP 403 (Forbidden), 404 (Not Found), or "Resource not accessible", re-run it through ghsudo. GitHub may return 404 instead of 403 for private resources when the token lacks sufficient permissions.

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

* `gh` command fails with "Projects (classic)" GraphQL error -> `gh` version is outdated, upgrade needed.
