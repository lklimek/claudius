---
name: review-pr
description: Audit and review a pull request. Use when asked to review, audit, or analyze a PR for code quality, security, and correctness.
allowed-tools: Read, Grep, Glob, Write, Bash(gh pr view *), Bash(gh pr comment *), Bash(gh api repos/*/pulls/*/reviews *), Bash(gh api repos/*/pulls/*/comments *), Bash(gh api repos/*/pulls/* --jq *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *)
---

# PR Audit Workflow

When asked to audit/review a PR, follow this workflow:

## 1. Gather Context

Prefer local git commands over `gh api` for performance.

```bash
# Determine the PR base (the commit v1.0-dev points to, or use gh only if needed)
BASE_BRANCH=v1.0-dev
gh pr view --json number,title,body,url

git log $BASE_BRANCH..HEAD --oneline
git diff $BASE_BRANCH...HEAD --stat
git diff $BASE_BRANCH...HEAD
```

## 2. Spawn Team
Create a team (`pr<NUMBER>-audit`) with parallel agents:

| Agent (`subagent_type`) | Task Focus |
|---|---|
| `code-reviewer` | Correctness, duplication, edge cases, behavioral changes |
| `security-engineer` | Injection, concurrency/deadlocks, race conditions, panics, DoS, known security issues |
| `rust-developer` / `go-developer` / `python-developer` | Language idioms, error handling, lock ordering, transaction safety |
| `technical-writer` | Documentation accuracy, README/CLAUDE.md updates, doc comments, changelog entries |

For large PRs, split `code-reviewer` by file. For small PRs, `code-reviewer` + `security-engineer` may suffice. Add `technical-writer` when the PR touches documentation, public APIs, or adds/changes user-facing behavior that should be documented.

Each task description must include: files to review, what changed, focus areas, `git show <base>:<file>` for comparison, "DO NOT write code", report format (severity + file:line + description + impact), and instruction to send findings via SendMessage.

## 3. Consolidate Findings
Compile summary table with severity: CRITICAL > HIGH > MEDIUM > LOW > INFO.

## 4. Post GitHub PR Review

Ask if your findings should be published as Github PR review.

The review is posted in **two parts**:

### Part A: Summary comment (visible immediately)

Post the audit summary as a normal PR issue comment using `gh pr comment`. This ensures the summary is always visible (draft reviews hide their body text). Include:
- **Attribution**: "Reviewed by: Claude Code" and list the team members with their roles
- Overall assessment
- Findings table (severity, location, description)
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

Post inline comments on specific diff lines as a draft review using `gh api`. This lets the user review and submit them manually.
For trivial changes, include edit suggestions using ```suggestion ``` blocks.

To post the review to the Github PR, use `gh api` with `--input` (NOT `--raw-field` for JSON arrays).

#### Verify lines are within the GitHub diff before posting

The GitHub diff may differ from the local `git diff` (e.g., when the PR base includes commits not yet in the local branch). Before constructing inline comments:

1. **Get the PR base SHA** that GitHub uses:
   ```bash
   gh api repos/<owner>/<repo>/pulls/<number> --jq '.base.sha'
   ```

2. **Check each file's diff hunks** to confirm your comment lines are within them. Use the local diff with the correct base:
   ```bash
   git diff <base-sha>...HEAD -- <file> | grep "^@@"
   ```
   A hunk `@@ -old,len +new,len @@` means new-file lines `new` through `new+len-1` are in the diff.

3. **If a finding's line is outside the diff**, move it to Part A (the summary comment), not an inline comment. GitHub rejects inline comments on lines outside the diff with HTTP 422 "Line could not be resolved".

#### Deduplicate before posting
Before creating a new review, fetch existing reviews and their inline comments to avoid duplicates. See the **github** skill (`PR Review Comments` section) for the fetch commands.

Drop any finding that already appears in an existing review body or inline comment (match by file:line and substance, not exact wording).

#### Draft mode
Reviews are posted as **drafts** (pending) so the user can review and submit manually.
To achieve this, **omit the `event` field** entirely — the GitHub API defaults to a pending/draft review.
The `body` field can be minimal (e.g., "See summary comment for full audit report") since the detailed summary is in Part A.

```bash
cat > /tmp/pr-review.json << 'ENDJSON'
{
  "commit_id": "<SHA>",
  "body": "See summary comment for full audit report.",
  "comments": [
    {"path": "src/file.rs", "line": 123, "side": "RIGHT", "body": "Inline comment"}
  ]
}
ENDJSON
gh api repos/<owner>/<repo>/pulls/<number>/reviews --method POST --input /tmp/pr-review.json --jq '.html_url'
```

Rules:
- **Never** include `"event"` in the JSON — omitting it creates a draft review
- Inline comments only on lines **within the diff**; everything else goes in Part A
- Use `side: "RIGHT"` for new code
- Get commit SHA: `git rev-parse HEAD` or `gh api repos/.../pulls/<n> --jq '.head.sha'`

## 5. Cleanup
Shutdown all agents (`SendMessage type: "shutdown_request"`), then `TeamDelete`.
