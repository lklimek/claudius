---
name: review-pr
description: Use to review a PR for code quality, security, and correctness.
agent: claudius
context: fork
allowed-tools: Read, Grep, Glob, Write, Bash(gh pr view *), Bash(gh pr comment *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-post-review.sh *), Bash(*gh-pr-base-sha.sh *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Task, TaskCreate, TaskUpdate, TaskList, TaskGet, SendMessage
---

# PR Audit Workflow

When asked to audit/review a PR, follow this workflow.

## 1. Gather PR Context

Prefer local git commands over `gh api` for performance.

```bash
BASE_BRANCH=$(gh pr view --json baseRefName -q .baseRefName)
gh pr view --json number,title,body,url

git log $BASE_BRANCH..HEAD --oneline
git diff $BASE_BRANCH...HEAD --stat
git diff $BASE_BRANCH...HEAD
```

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

#### Verify lines are within the GitHub diff before posting

The GitHub diff may differ from the local `git diff` (e.g., when the PR base includes commits not
yet in the local branch). Before constructing inline comments:

1. **Get the PR base SHA** that GitHub uses:
   ```bash
   ../../scripts/gh-pr-base-sha.sh <owner> <repo> <number>
   ```

2. **Check each file's diff hunks** to confirm your comment lines are within them. Use the local
   diff with the correct base:
   ```bash
   git diff <base-sha>...HEAD -- <file> | grep "^@@"
   ```
   A hunk `@@ -old,len +new,len @@` means new-file lines `new` through `new+len-1` are in the diff.

3. **If a finding's line is outside the diff**, move it to Part A (the summary comment), not an
   inline comment. GitHub rejects inline comments on lines outside the diff with HTTP 422.

#### Deduplicate before posting

Before creating a new review, fetch existing reviews and their inline comments to avoid duplicates.
See the **git-and-github** skill (`PR Review Comments` section) for the fetch commands.

Drop any finding that already appears in an existing review body or inline comment (match by
file:line and substance, not exact wording).

#### Draft mode

Reviews are posted as **drafts** (pending) so the user can review and submit manually.
The `gh-post-review.sh` wrapper enforces draft mode by stripping any `event` field from the input
JSON. The `body` field can be minimal since the detailed summary is in Part A.

```bash
SESSION_DIR=$(mkdir -p /tmp/claude && mktemp -d /tmp/claude/XXXXXX)
cat > "$SESSION_DIR/pr-review.json" << 'ENDJSON'
{
  "commit_id": "<SHA>",
  "body": "See summary comment for full audit report.",
  "comments": [
    {"path": "src/file.rs", "line": 123, "side": "RIGHT", "body": "Inline comment"}
  ]
}
ENDJSON
../../scripts/gh-post-review.sh <owner> <repo> <number> "$SESSION_DIR/pr-review.json"
```

Rules:
- The script strips `"event"` automatically — reviews are always posted as drafts
- **Only actionable findings** (CRITICAL/HIGH/MEDIUM/LOW) become inline comments; INFO goes in Part A only
- Inline comments only on lines **within the diff**; everything else goes in Part A
- Use `side: "RIGHT"` for new code
- Get commit SHA: `git rev-parse HEAD`

## 4. Cleanup

Shutdown all agents (`SendMessage type: "shutdown_request"`), then `TeamDelete` (if a team was
used).
