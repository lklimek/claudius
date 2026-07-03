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

1. Verify you're on a base branch — if on an unrelated feature branch, switch to base or confirm with user.
2. Pull (fast-forward only). On diverged history, rebase if trivial, otherwise alert user.
3. Search open PRs for related fixes — don't duplicate work already in progress.

## Committing

Create feature branches. NEVER commit to base branch.

Stage specific files -- never `git add .` or `git add -A`.

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`). Append `!` for breaking changes.

Commit message format (always use HEREDOC). Substitute `<your-model-name>` with your own actual current model — never copy a version literally from this doc, it will always eventually go stale:

```bash
git add <file1> <file2>
git commit -m "$(cat <<'EOF'
<type>: <description>

<optional body>

Co-Authored-By: Claude <your-model-name> <noreply@anthropic.com>
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

The PR body **must lead with a `## Why this PR exists` section** — reviewers read motivation before mechanics. Use this skeleton (drop empty sections):

```markdown
## Why this PR exists
- **Problem**: 1-2 plain-language sentences on what's broken or missing.
- **What breaks without it**: a concrete reproduction or threat scenario — numbered steps or a short narrative showing the actual failure/misbehaviour, not an abstract claim.
- **Blocking relationship**: prerequisite for / depends on / stacked atop PR #N, if any.

## What was done
## Testing
## Breaking changes
## Checklist
## Attribution
```

`Why this PR exists` comes first; the remaining sections follow in that order. Always create PRs as drafts.

**PR descriptions describe net final state only** — no development history, changelog, or step-by-step iteration/debugging narrative; that belongs in commit messages. Concise final testing/verification results (the `## Testing` section) describe the final state, not history, and are expected.

### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft/pending reviews.** The user must publish the review themselves. When using MCP, omit the `event` field in `pull_request_review_write` to create a pending review.

See [pr-review.md](references/pr-review.md) for the full procedure: fetching PR context, deduplication, diff-bounds verification, and posting inline comments.

### Issues

Before creating, search existing issues (open + closed) and PRs for duplicates. If found, show to user and ask before proceeding. Check for issue templates. Always append attribution footer.

**Feature/enhancement issues must include a `### User Story` section** -- an informal story describing what the user can achieve (no technical details). Start with "As a **\<persona\>**, I want to ... so that ...". Multiple personas are fine. Place user stories before technical details.

## Safety Rules

1. **Always ask before pushing or publishing to GitHub** -- pushes, PRs, issues, comments, reviews. Commits are local and don't require confirmation, but pushes always do.
2. **Never force-push. Never amend commits.** Always create new commits. If force-push is needed, ask the user to do it manually.
3. **Never use `git add .` or `git add -A`** -- stage specific files
4. **Never use interactive flags** (`-i`) -- requires terminal input
5. **Never skip hooks** (`--no-verify`) unless explicitly requested
6. **Check for `.env`, credentials, or secret files** before staging -- warn if found
7. **Check for PR/issue templates** before creating -- use them if they exist
8. **Avoid `gh api`** -- prefer MCP tools or high-level `gh` subcommands. Use `gh api` only for read-only queries when no subcommand or MCP tool exists. Never use `gh api` for write operations. Exception: `gh api graphql` for mutations with no MCP/CLI equivalent (e.g., thread resolution).
9. **Never fork repositories** -- on access denied (403/404), use `ghsudo` to elevate permissions or ask the user. Forking creates a separate repo and breaks the workflow. This applies to both `gh repo fork` and `fork_repository` MCP tool.
10. **Sandbox and `gh`/`ghsudo` CLI** -- these commands need network access to `api.github.com`. The recommended fix is adding `"api.github.com"` to `sandbox.network.allowedDomains` in `settings.json` — this lets `gh` work inside the sandbox without disabling it. If that's not configured and `gh` fails with network errors, use `dangerouslyDisableSandbox: true` on the Bash tool call as a fallback. MCP tools (`mcp__plugin_claudius_github__*`) bypass the sandbox and are unaffected.

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

### GitHub MCP PR Body Formatting

When passing a `body` parameter to `create_pull_request` or `update_pull_request` MCP tools, use actual multi-line strings — NOT `\n` escape sequences on a single line. MCP tools pass the string directly to the API; `\n` renders as literal backslash-n on GitHub instead of a newline.

## Requesting Reviewers

Use `gh-request-reviewer.sh` for all reviewer requests — supports multiple reviewers and `@copilot`:

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-request-reviewer.sh <owner/repo> <pr_number> <reviewer> [reviewer ...]
```

`@copilot` reviewer syntax requires `gh` ≥ 2.88.0. If requesting review fails, check `gh --version` and escalate to the user if upgrade is needed.

## Elevated Permissions (ghsudo) -- Optional Fallback

If a `gh` or `git` command fails with 403/404 or "Resource not accessible", use [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`) to retry with elevated permissions. **Never fork the repository as a workaround** -- forking creates a separate repo and breaks push/PR workflows. See [gh-cli-fallback.md](references/gh-cli-fallback.md) for full usage and exit codes.
