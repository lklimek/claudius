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

### Issues

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

## Escaping and Formatting

- Use HEREDOCs (`<<'EOF'`) for multi-line bodies
- When using `gh api` (read-only only), prefer `--jq` over `| jq` -- `--jq` is processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion)

## Elevated Permissions (ghsudo) -- Optional Fallback

If you use a **read-only default token** with `gh`, install [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) for write operations. When a `gh` or `git` command fails with HTTP 403 (Forbidden), 404 (Not Found), or "Resource not accessible", re-run it through ghsudo. GitHub may return 404 instead of 403 for private resources when the token lacks sufficient permissions.

ghsudo auto-detects the target org from `-R owner/repo` flags or the current repo's git remote. It shows a GUI popup (or terminal prompt) with the exact command and org, asking the user to approve. If approved, it re-executes the command with the org's stored read-write token.

- Exit code 4 -> no token stored. Tell the user to run `ghsudo --setup <org>` to configure their read-write PAT.
- Exit code 2 -> user denied the request. Do not retry.
- Exit code 3 -> no GUI and no terminal available. Inform the user.
