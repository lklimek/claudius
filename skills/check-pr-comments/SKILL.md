---
name: check-pr-comments
description: Verify whether existing PR review comments have been addressed in code. Checks out the branch, verifies each comment against current code, resolves addressed threads, and produces a structured JSON report compatible with triage-findings. Use when asked to check, triage, or verify PR review feedback.
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr view *), Bash(gh pr checkout *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-list-review-threads.sh *), Bash(*gh-resolve-review-thread.sh *), Bash(git pull *), Bash(git fetch *), Bash(*validate_report.py *), Bash(*generate_review_report.py *)
---

# Check PR Comments Workflow

When asked to check/triage/verify existing PR review comments, follow this workflow.

## 1. Fetch All Comments

Fetch inline review comments, PR-level comments, and review summaries. See the **github** skill (`PR Review Comments` section) for the wrapper scripts.

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

## 4. Build Structured Report JSON

Produce a `report.json` file following the unified report schema (`schemas/review-report.schema.json` v1.1.0).

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
  "severity": "INFO for RESOLVED, assessed severity for UNRESOLVED",
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

- **Resolved** comments: `severity: "INFO"`, `verdict: "RESOLVED"`. `recommendation` describes what was done.
- **Unresolved** comments: assessed severity (CRITICAL > HIGH > MEDIUM > LOW), `verdict: "UNRESOLVED"`. `recommendation` describes what still needs to be done.
- Severity levels: see `severity` skill.
- `thread_id`: from `gh-list-review-threads.sh` output. Needed for thread resolution in step 7.

### Numbering

Assign sequential IDs: `CMT-001`, `CMT-002`, etc. Order: unresolved first (by severity descending), then resolved.

## 5. Validate Report

```bash
python3 scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 6. Render and Present

```bash
python3 scripts/generate_review_report.py report.json --format md
```

Present the rendered markdown report to the user. Optionally generate HTML (`--format html`) for richer display.

The user can also invoke `triage-findings report.json` for interactive browser-based triage of unresolved comments.

## 7. Resolve Addressed Threads

**Always ask the user for confirmation before resolving any threads.**

After the report is presented and the user approves, resolve addressed review threads. See the **github** skill (`PR Review Comments > Resolving review threads` section) for the wrapper scripts.

Only resolve threads where verification confirms the issue is fixed. Never resolve threads that are only partially addressed.
