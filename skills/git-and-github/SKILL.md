---
name: git-and-github
description: Invoke for all git and gh commands, GitHub interactions. Solves git and gh access / permission denied issues.
---

# GitHub Workflow

Use `git` for repository operations (clone, fetch, commit, push, branch, merge). Use GitHub MCP for GitHub-specific operations (PRs, issues, releases, Actions, checks).

**Tooling**: Prefer GitHub MCP server tools (`mcp__plugin_claudius_github__*`) for all GitHub API operations -- PRs, issues, reviews, actions, branches, releases, security alerts. If GitHub MCP is unavailable, read [gh-cli-fallback.md](references/gh-cli-fallback.md) for `gh` CLI equivalents.

**Attribution**: Every commit, PR, issue, and comment posted to GitHub **must** include this footer (blank line before it):

```
<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
```

## Before Starting Work

**Branch check**: Verify you are on the base branch (e.g., `main`, `master`, `develop`) before starting new work. If on an unrelated feature branch, switch to base first. If the current feature branch is related, confirm with the user before continuing on it.

Always pull the current branch (fast-forward only) before starting any work. If the pull fails due to diverged history, rebase when the conflict is trivial (few files, obvious resolution). Otherwise alert the user — never force-merge without explicit permission.

**Dedup check**: Before starting work on an issue or bug, search open PRs (`search_pull_requests` or `list_pull_requests`) for related fixes already in progress. If a PR addresses the same issue, inform the user instead of duplicating effort.

## Committing

Create feature branches. NEVER commit to base branch.

Stage specific files -- never `git add .` or `git add -A`.

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`). Append `!` for breaking changes.

Commit message format (always use HEREDOC):

```bash
git add <file1> <file2>
git commit -m "$(cat <<'EOF'
<type>: <description>

<optional body>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

## Changelog

When editing `CHANGELOG.md`, follow [Keep a Changelog](https://keepachangelog.com/) format.

## Pushing

If a push fails with 403 or "Resource not accessible" and `ghsudo` is installed, retry through ghsudo (see [Elevated Permissions](#elevated-permissions-ghsudo--optional-fallback)).

**Always ask the user for explicit confirmation before every push.** Never push automatically -- even after committing or creating a PR. Even if the user agreed to push earlier, ask again before next push.

**Never force-push. Never amend commits.** Always create new commits. If force-push is required, ask the user to do it manually.

## Pull Requests

### Creating a PR

Check for a PR template first. If a template exists, read and fill it in. When applicable, include an informal user story (what the user can achieve, no technical details -- start with "Imagine you are...").

Always create PRs as drafts.

### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft/pending reviews.** The user must publish the review themselves. When using MCP, omit the `event` field in `pull_request_review_write` to create a pending review.

See [pr-review.md](references/pr-review.md) for the full procedure: fetching PR context, deduplication, diff-bounds verification, and posting inline comments.

### Issues

**Dedup check**: Before creating an issue, search existing issues — both open and closed (`search_issues` or `list_issues` with `state=all`) — for duplicates or related reports. If a likely duplicate exists, show it to the user and ask before proceeding.

Check for issue templates before creating. Always append attribution footer.

**Feature/enhancement issues must include a `### User Story` section** -- an informal story describing what the user can achieve (no technical details). Start with "As a **\<persona\>**, I want to ... so that ...". Multiple personas are fine. Place user stories before technical details.

## Safety Rules

1. **Always ask before pushing or publishing to GitHub** -- pushes, PRs, issues, comments, reviews. Commits are local and don't require confirmation, but pushes always do.
2. **Never force-push. Never amend commits.** Always create new commits. If force-push is needed, ask the user to do it manually.
3. **Never use `git add .` or `git add -A`** -- stage specific files
4. **Never use interactive flags** (`-i`) -- requires terminal input
5. **Never skip hooks** (`--no-verify`) unless explicitly requested
6. **Check for `.env`, credentials, or secret files** before staging -- warn if found
7. **Check for PR/issue templates** before creating -- use them if they exist
8. **Avoid `gh api`** -- prefer MCP tools or high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand or MCP tool exists. Never use `gh api` for write operations.

## Context Management — Large MCP Responses

GitHub MCP tools can return 10k+ tokens (file lists, diffs, review threads, CI logs), polluting the calling agent's context window with data that's only needed briefly.

**Solution**: Delegate large MCP operations to a disposable subagent via the Agent tool. The subagent calls the MCP tool, extracts what's needed, and returns only a concise summary. Its full context is discarded after completion.

**Delegate these** (unbounded/large responses):
- `pull_request_read` with `get_files` — file lists on large PRs
- `pull_request_read` with `get_diff` — full PR diffs
- `pull_request_read` with `get_review_comments` — PRs with many threads
- `get_job_logs` — CI logs (10k+ tokens typical)
- `list_*` and `search_*` operations with many results

**Safe to call directly** (bounded data): single PR metadata (`get`), single issue, branch list, single commit.

**Pattern**:
```
Agent(
  subagent_type="Explore",
  prompt="Fetch changed files for PR #123 in owner/repo using pull_request_read (get_files). Return only: file paths with +/- line counts and total stats."
)
```

Use `Explore` for read-only extraction (has MCP tools, no Edit/Write). Use `general-purpose` when writes are needed.

**Key principle**: Tell the subagent exactly what to extract and what format to return. Not "fetch PR data" but "fetch changed file list, return file paths with +/- line counts, total stats."

## Escaping and Formatting

- Use HEREDOCs (`<<'EOF'`) for multi-line bodies
- When using `gh api` (read-only only), prefer `--jq` over `| jq` -- `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion)

## Elevated Permissions (ghsudo) -- Optional Fallback

If a `gh` or `git` command fails with 403/404 or "Resource not accessible", use [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) to retry with elevated permissions. See [gh-cli-fallback.md](references/gh-cli-fallback.md) for full usage and exit codes.
