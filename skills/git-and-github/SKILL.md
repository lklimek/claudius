---
name: git-and-github
description: Invoke for all git and gh commands, GitHub interactions. Solves git and gh access / permission denied issues.
---

# GitHub Workflow

**Tooling**: `git` for repository operations (clone, fetch, commit, push, branch, merge); GitHub MCP tools (`mcp__plugin_claudius_github__*`) for all GitHub API operations (PRs, issues, reviews, Actions, checks, branches, releases, security alerts). If MCP is unavailable, read [gh-cli-fallback.md](references/gh-cli-fallback.md) for `gh` CLI equivalents. Bare coordinator sessions typically lack these tools and should default directly to the CLI fallback; spawned agents whose frontmatter lists them still prefer MCP.

**Attribution**: every commit, PR, issue, and comment posted to GitHub **must** include this footer (blank line before it):

```
<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
```

## Before Starting Work

1. Verify you're on a base branch — if on an unrelated feature branch, switch to base or confirm with user.
2. Pull (fast-forward only). On diverged history, rebase if trivial, otherwise alert user.
3. Search open PRs for related fixes — don't duplicate in-progress work.

## Committing

Create feature branches. NEVER commit to base branch.

Stage specific files — never `git add .` or `git add -A`.

Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`); append `!` for breaking changes.

Commit format (always HEREDOC). Substitute `<your-model-name>` with your actual current model — never copy a version literally from this doc, it goes stale:

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

Edit `CHANGELOG.md` per [Keep a Changelog](https://keepachangelog.com/) format.

## Pushing

If a push fails with 403 or "Resource not accessible" and `ghsudo` is installed, retry through it (see [Elevated Permissions](#elevated-permissions-ghsudo----optional-fallback)).

Always ask explicit confirmation before every push, even if the user agreed earlier — see Safety Rules.

## Pull Requests

### Creating a PR

Check for a PR template first; if one exists, fold its required content into the skeleton linked below rather than replacing it.

The PR body **must lead with a plain-language summary before any implementation detail** — a technical product manager or external reviewer with no code context must understand everything before `Detailed discussion` at a glance. Fill in the skeleton from [pr-body-template.md](references/pr-body-template.md) (fenced block only, not the page's title or prose).

**`TL;DR` / `User story` / `Scenario` are user-facing** — plain language only: no specialized terms, internal implementation details, or code identifiers. Describe strictly user-observable behavior (for an API/CLI, the calling developer *is* the user). `User story` uses the same "As a `<role>`..." shape as Issues below, phrased for a change already made. `Scenario` isn't only for bugs: for a new feature, `Actual behavior` is what's missing/impossible today, `Expected behavior` is what becomes possible after this PR — no failure required. For a pure internal change with no user-observable effect, drop `User story` and `Scenario` and say so in `Detailed discussion`. Note blocking relationships (prerequisite for / depends on / stacked atop PR #N) in `Detailed discussion`.

**`Detailed discussion` is for implementors and AI agents** — as technical as needed: problem/rationale, code-level specifics, the sub-sections above.

`TL;DR` → `User story` → `Scenario` → `Detailed discussion`, in that order. Always create PRs as drafts.

**PR descriptions describe net final state only** — no development history, changelog, or iteration/debugging narrative; that belongs in commit messages. `### Actual behavior` (the pre-existing problem being solved) and concise final `### Testing` results describe state, not history, and are expected.

### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft/pending reviews** — the user publishes them. With MCP, omit the `event` field in `pull_request_review_write` to create a pending review.

See [pr-review.md](references/pr-review.md) for the full procedure: fetching PR context, deduplication, diff-bounds verification, posting inline comments, and the `add_comment_to_pending_review` parameter-casing requirement.

### Issues

Before creating, search existing issues (open + closed) and PRs for duplicates — if found, show the user and ask before proceeding. If an issue template exists, fold its required content into the skeleton rather than replacing it.

Issue bodies use the same plain-language-first skeleton as PRs (see §Creating a PR): fill in [issue-body-template.md](references/issue-body-template.md) (fenced block only) — `TL;DR` → `User story` → `Scenario` → `Detailed discussion`. `User story` uses the same "As a **\<role\>**, I want to ..., to achieve ..." shape as PRs — multiple personas fine, repeat the line. Append the attribution footer last.

## Safety Rules

1. **Always ask before pushing or publishing to GitHub** — pushes, PRs, issues, comments, reviews. Commits are local and need no confirmation; pushes always do.
2. **Never force-push. Never amend commits.** Always create new commits. If force-push is needed, ask the user to do it manually.
3. **Never `git add .` or `git add -A`** — stage specific files
4. **Never use interactive flags** (`-i`) — they require terminal input
5. **Never skip hooks** (`--no-verify`) unless explicitly requested
6. **Check for `.env`, credentials, or secret files** before staging — warn if found
7. **Check for PR/issue templates** before creating — use them if they exist
8. **Avoid `gh api`** — prefer MCP tools or high-level `gh` subcommands. Use `gh api` only for read-only queries with no subcommand/MCP equivalent; never for writes. Exception: `gh api graphql` for mutations with no MCP/CLI equivalent (e.g., thread resolution).
9. **Never fork repositories** — on access denied (403/404), use `ghsudo` or ask the user. Forking creates a separate repo and breaks the workflow. Applies to both `gh repo fork` and the `fork_repository` MCP tool.
10. **Sandbox and `gh`/`ghsudo` CLI** — these need network access to `api.github.com`. Preferred fix: add `"api.github.com"` to `sandbox.network.allowedDomains` in `settings.json` — `gh` then works inside the sandbox. If unconfigured and `gh` fails with network errors, fall back to `dangerouslyDisableSandbox: true` on the Bash call. MCP tools bypass the sandbox and are unaffected.

## Context Management — Large MCP Responses

GitHub MCP tools can return 10k+ tokens (file lists, diffs, review threads, CI logs), polluting the caller's context with briefly-needed data.

**Solution**: delegate large MCP calls to a disposable subagent (Agent tool) that extracts what's needed and returns a concise summary; its context is discarded after completion.

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

Use `Explore` for read-only extraction (has MCP tools, no Edit/Write); `general-purpose` when writes are needed.

**Key principle**: tell the subagent exactly what to extract and what format to return — not "fetch PR data" but "fetch changed file list, return file paths with +/- line counts, total stats."

## Escaping and Formatting

- Use HEREDOCs (`<<'EOF'`) for multi-line bodies
- With `gh api` (read-only only), prefer `--jq` over `| jq` — processed internally by `gh`, avoiding shell expansion issues (`!` triggers history expansion)

### GitHub MCP PR Body Formatting

Pass `body` to `create_pull_request` / `update_pull_request` as an actual multi-line string — NOT `\n` escapes on a single line. MCP passes the string straight to the API; `\n` renders as literal backslash-n on GitHub.

## Requesting Reviewers

Use `gh-request-reviewer.sh` for all reviewer requests — supports multiple reviewers and `@copilot`:

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-request-reviewer.sh <owner/repo> <pr_number> <reviewer> [reviewer ...]
```

`@copilot` requires `gh` ≥ 2.88.0 — on failure, check `gh --version` and escalate to the user if an upgrade is needed.

## Elevated Permissions (ghsudo) -- Optional Fallback

If a `gh` or `git` command fails with 403/404 or "Resource not accessible", retry via [ghsudo](https://github.com/lklimek/ghsudo) (`pip install ghsudo`). **Never fork the repository as a workaround.** See [gh-cli-fallback.md](references/gh-cli-fallback.md) for full usage and exit codes.
