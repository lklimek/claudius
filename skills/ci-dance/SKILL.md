---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh label *), Bash(git *)
---

# CI Dance

End-to-end PR pipeline: push changes, make CI green, request and address reviews, repeat until no actionable feedback remains.

## Prerequisites

- Load `claudius:git-and-github` skill first — all git, gh, and GitHub conventions come from there
- Working tree has changes to push, or commits already pushed to a remote branch
- Remote is configured (`git remote -v` shows an origin)
- CI workflows exist for the repository

## Pipeline Steps

### 1. Push

Invoke `/push` to commit, push, and create or update the PR.

### 2. Make CI Green

Invoke `/ci-loop` to monitor CI, diagnose failures, apply fixes, and push until all workflow runs pass.

### 3. Request Reviews

After CI is green, request reviews and label the PR. Skip gracefully on any errors (reviewer not available, label doesn't exist).

```bash
gh pr edit --add-reviewer @copilot || true
gh pr edit --add-label claudius-review || true
```

### 4. Wait for Reviews

Poll for new reviews using the approach described in `/review-loop` (Steps 2-3). Timeout after 30 minutes if no review arrives — report to the user and stop waiting.

### 5. Check and Fix Review Comments

Invoke `/check-pr-comments` to verify review comments against the current code and identify actionable issues.

For each actionable comment:
- Apply the fix locally.
- Commit the change.

If no actionable comments remain, proceed to the exit check.

### 6. Push Fixes and Repeat

Invoke `/push` to push all fixes. Then go back to **Step 2** to run CI again. After CI is green, go to **Step 3** to re-request review.

Repeat the outer loop (Steps 2-6) until the exit conditions are met.

## Exit Conditions

- **Success**: CI is green and the latest review has no actionable comments. Report loop counts and remind the user to merge.
- **Timeout**: 60 minutes elapsed since the skill started — stop, report progress and current state to the user.
- **Stuck**: The same CI failure or review comment persists after 2-3 fix attempts — stop, report what was tried, and ask the user for guidance.

## Final Report

On exit (any condition), report:

- Overall outcome (success / timeout / stuck)
- Number of CI loop iterations executed
- Number of review loop iterations executed
- Any unresolved issues

## Notes

- No confirmation required — invocation implies intent.
- NEVER merge the PR. Merging is the user's responsibility.
- Track the loop start time at invocation. Check elapsed time before each iteration of the outer loop.
- Do not duplicate logic from sub-skills — delegate fully to `/push`, `/ci-loop`, `/check-pr-comments`, and the review polling approach in `/review-loop`.
