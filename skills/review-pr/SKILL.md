---
name: review-pr
description: Use to review a PR for code quality, security, and correctness.
agent: claudius
context: fork
allowed-tools: Read, Grep, Glob, Write, Bash(gh pr comment *), Bash(*gh-post-review.sh *), Bash(*gh-pr-base-sha.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Task, TaskCreate, TaskUpdate, TaskList, TaskGet, SendMessage, mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_issue_comment, mcp__plugin_claudius_github__pull_request_review_write, mcp__plugin_claudius_github__add_comment_to_pending_review
---

# PR Audit Workflow

When asked to audit/review a PR, follow this workflow.

## 1. Gather PR Context

Load /claudius:git-and-github skill .

Use GitHub MCP to fetch PR metadata:

- **PR details**: `pull_request_read` with `method: "get"` — returns title, body, URL, base/head branches, number.
- **Changed files**: `pull_request_read` with `method: "get_files"` — returns list of changed files with stats.
- **PR diff**: `pull_request_read` with `method: "get_diff"` — returns the full diff.

Use local git for commit history and detailed diffs.

If GitHub MCP is unavailable, see [gh-cli-fallback.md](../git-and-github/references/pr-review.md) for `gh` CLI equivalents.

## 2. Conduct the Review

Invoke the `/claudius:grumpy-review` skill with the PR scope as the argument. It covers:
- Agent selection and scaling based on PR size
- Parallel agent spawning with explicit prompts
- OWASP classification on all security findings
- Consolidated, deduplicated report generation

Pass the PR's scope (changed files, base branch) as context to the review methodology.

## 3. Post GitHub PR Review

Ask if findings should be published as a GitHub PR review.

The review is posted in **two parts**:

### Part A: Summary comment (visible immediately)

Post the audit summary as a normal PR issue comment using `gh pr comment`. This ensures the
summary is always visible (draft reviews hide their body text). Include:
- **Attribution**: "Reviewed by: Claude Code" and list the team members with their roles
- Overall assessment
- Findings table (severity, OWASP tag, location, description)
- Pre-existing / outside-diff issues with details
- Positive observations

```bash
gh pr comment <number> --body "$(cat <<'EOF'
## Audit Summary

**Reviewed by:** Claude Code with a N-agent team:
- `agent-name` (agent-type) — focus area
...

[Summary text, findings table, pre-existing issues, positive observations]
EOF
)"
```

### Part B: Inline comments (draft review)

Post **only actionable findings** (CRITICAL, HIGH, MEDIUM, LOW) as inline comments on specific
diff lines. **Do not post INFO-level findings as inline comments** — INFO findings are positive
observations (praise, good patterns) and belong in Part A only. Non-actionable comments clutter
the review and waste the reviewer's time.

Post as a draft review so the user can review and submit manually. For trivial changes, include
edit suggestions using ```suggestion ``` blocks.

#### Posting inline comments

See [gh-cli-fallback.md](../git-and-github/references/pr-review.md) for: verifying diff bounds (get base SHA, check hunks), deduplication (fetch existing reviews/comments first), and posting with `gh-post-review.sh`. The `body` field can be minimal since the detailed summary is in Part A.

## 4. Cleanup

Shutdown all agents (`SendMessage type: "shutdown_request"`), then `TeamDelete` (if a team was
used).
