---
name: check-pr-comments
description: Use to verify PR review comments are addressed in code. Optionally produces triage-compatible report.
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr checkout *), Bash(gh pr view *), Bash(git pull *), Bash(git fetch *), Bash(*validate_report.py *), Bash(*generate_review_report.py *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-list-review-threads.sh *), Bash(*gh-resolve-review-threads.sh *), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment
---

# Check PR Comments Workflow

When asked to check/triage/verify existing PR review comments, follow this workflow.

## 1. Fetch All Comments

**ALWAYS fetch fresh comments from GitHub on every invocation.** Never assume you already have them or that there are no new ones -- comments may have just appeared.

Use GitHub MCP tools to fetch all comment types:

- **Review threads** (inline comments with resolution status): `pull_request_read` with `method: "get_review_comments"` — returns threads with `isResolved`, `isOutdated`, `isCollapsed` metadata and grouped comments.
- **Review summaries**: `pull_request_read` with `method: "get_reviews"` — returns review state, body, and author.
- **PR-level comments** (non-diff): `pull_request_read` with `method: "get_comments"` — returns general PR discussion.

Paginate with `perPage` and `page` (for get_reviews/get_comments) or `perPage` and `after` cursor (for get_review_comments) to fetch all results.

If GitHub MCP is unavailable, see [gh-cli-fallback.md](references/gh-cli-fallback.md) for `gh` CLI equivalents.

## 2. Checkout and Pull the PR Branch

```bash
gh pr checkout <number>
git pull
```

## 3. Verify Each Comment Against Current Code

For every inline comment, read the file at the referenced location and **verify whether the identified issue is actually fixed** -- not just whether the code changed. Specifically:

- Read the current code at the location the comment references
- Understand what the comment is asking for
- Determine if the current code satisfies the request (semantically, not just syntactically)
- For comments with multiple sub-items, verify each one independently
- A comment is only "resolved" if **all** of its sub-items are addressed
- Verify the fix achieves the intended end-user or developer experience, not just technical correctness

## 4. Present Summary

Present a concise summary directly to the user:
- Total comments checked, how many resolved vs unresolved
- For **each comment**, include Claude's assessment:
  - **Resolved**: confirm the fix is adequate, or flag remaining concerns if the resolution is technically present but semantically incomplete. State whether you agree the original comment was valid.
  - **Unresolved**: state your recommendation (priority and suggested approach). If you disagree with the reviewer's concern, say so with a brief reason.
- Lead with unresolved comments, then resolved

This is the default end of the workflow. Steps 5-7 (structured report) are only produced when the user explicitly requests it (e.g. "generate report", "produce report", "with report"). Step 8 (resolve threads) applies to both flows.

---

## Optional: Structured Report (on request only)

## 5. Build Structured Report JSON

Produce a `report.json` file following the unified report schema (`../../schemas/review-report.schema.json` v2.0.0).

### Report structure

```json
{
  "schema_version": "1.1.0",
  "metadata": {
    "project": "<owner>/<repo>",
    "date": "YYYY-MM-DD",
    "branch": "<pr-branch>",
    "commit": "<HEAD short SHA>",
    "scope": "PR #<number> comment verification",
    "reviewers": ["<unique reviewer usernames>"],
    "report_type": "comment_check",
    "pr_number": <number>
  },
  "executive_summary": {
    "overall_assessment": "X of Y review comments resolved",
    "verdict_action": "N comments require attention"
  },
  "summary_statistics": {
    "total_findings": <total>,
    "severity_counts": { "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0 },
    "verdict_counts": { "RESOLVED": <n>, "UNRESOLVED": <n> }
  },
  "findings": [
    {
      "title": "PR Comment Verification",
      "category": "pr_comments",
      "findings": [ ... ]
    }
  ]
}
```

### Finding format

Each review comment becomes one finding:

```json
{
  "id": "CMT-001",
  "severity": 1,
  "title": "Short description of what the comment requests",
  "location": "path/to/file.rs:42-56",
  "description": "What the comment asked for (multi-line OK)",
  "recommendation": "What was done (RESOLVED) or what to do (UNRESOLVED)",
  "reviewer": "github-username",
  "comment_id": 12345678,
  "comment_url": "https://github.com/<owner>/<repo>/pull/<number>/files#r<commentId>",
  "thread_id": "GraphQL-node-ID-for-thread-resolution",
  "verdict": "RESOLVED or UNRESOLVED"
}
```

- **Resolved** comments: `severity: 1` (INFO), `verdict: "RESOLVED"`. `recommendation` describes what was done.
- **Unresolved** comments: assessed numeric severity (5=CRITICAL, 4=HIGH, 3=MEDIUM, 2=LOW), `verdict: "UNRESOLVED"`. `recommendation` describes what still needs to be done.
- Severity mapping: 5=CRITICAL, 4=HIGH, 3=MEDIUM, 2=LOW, 1=INFO. See `severity` skill for definitions.
- `thread_id`: from `pull_request_read` `get_review_comments` response (or `gh-list-review-threads.sh` fallback). Needed for thread resolution in step 8.

### Numbering

Assign sequential IDs: `CMT-001`, `CMT-002`, etc. Order: unresolved first (by severity descending), then resolved.

## 6. Validate Report

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 7. Render and Present

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py report.json --format md
```

Present the rendered markdown report to the user. Optionally generate HTML (`--format html`) for richer display.

The user can also invoke `triage-findings report.json` for interactive browser-based triage of unresolved comments.

## CI Log Retrieval

See `git-and-github` skill § Context Management for the subagent delegation pattern. CI logs via `get_job_logs` are a prime example — always delegate to a subagent that fetches the log and extracts relevant failure information.

## 8. Resolve Addressed Threads

**Always ask the user for confirmation before resolving any threads.**

**Note:** Thread resolution uses `gh api graphql` via the wrapper script, which requires `dangerouslyDisableSandbox: true` on the Bash tool call. The orchestrator must use sandbox-disabled mode for this step.

After the summary (or report) is presented and the user approves, resolve addressed review threads using the wrapper script:

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <thread_id> [thread_id ...]
```

Thread resolution has no MCP equivalent — the wrapper script uses a GraphQL mutation directly.

Only resolve threads where verification confirms the issue is fixed. Never resolve threads that are only partially addressed.
