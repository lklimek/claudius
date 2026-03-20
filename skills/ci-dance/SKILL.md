---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh label *), Bash(gh run *), Bash(git *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(*gh-resolve-review-threads.sh *), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment
---

# CI Dance — Unattended PR Pipeline

Fully autonomous loop: push → CI green → bot review → fix MEDIUM+ findings → push → repeat. No confirmations, no user interaction until done or stuck.

## Prerequisites

- Load `claudius:git-and-github` skill first
- Working tree has changes to push, or commits already pushed to a remote branch
- Remote is configured and CI workflows exist

## Unattended Mode

- **No confirmations** — invocation implies full consent to push, fix, and re-push
- **Override sub-skill confirmations** — when invoking `/ci-loop`, `/push`, `/review-loop`, or `/check-pr-comments`, skip their "ask user" steps. This skill's invocation is the confirmation
- **Push freely** — commit and push fixes without asking
- **NEVER merge** — merging is always the user's responsibility

## Timeout

Record `start_time` at invocation. Before each loop iteration, check elapsed time. **Hard stop at 60 minutes** — exit immediately with a status report.

## Main Loop

```
LOOP (until exit condition met):
  1. PUSH        — commit, push, create/update PR
  2. CI          — watch runs, fix failures, push fixes, repeat until green
  3. REVIEW      — request bot review, wait, read comments, fix MEDIUM+, push
  4. CHECK EXIT  — if CI green AND no MEDIUM+ comments → SUCCESS
```

### Step 1: Push

Invoke `/push` to commit staged/unstaged changes, push, and create or update the PR. Skip user confirmation per unattended mode.

If nothing to commit or push, proceed to Step 2.

### Step 2: Make CI Green

Invoke `/ci-loop` to monitor all workflow runs, diagnose failures, apply fixes, and push. Skip its user confirmation step.

- If CI passes → proceed to Step 3
- If stuck after 2-3 attempts on same failure → EXIT STUCK
- Check timeout before each fix-push cycle

### Step 3: Bot Review

#### 3a. Request review

```bash
gh pr edit --add-reviewer @copilot || true
gh pr edit --add-label claudius-review || true
```

#### 3b. Wait for review (minimum 10 minutes)

Poll for new reviews using `gh-fetch-reviews.sh` (see `git-and-github` skill). Compare review IDs — a new review has a higher ID than the last known one.

- Poll interval: 30 seconds
- **Minimum wait: 10 minutes** — even if a review appears earlier, wait the full 10 minutes to allow all bots to finish
- Maximum wait: 15 minutes — if no review appears after 15 minutes, skip to Step 4 (CI is already green, so this is still a valid exit path)

#### 3c. Read and filter comments

Fetch inline comments from the latest review using `/check-pr-comments` workflow (Steps 1-3). Skip its confirmation steps.

**Severity filter**: only act on findings rated **MEDIUM (3) or above**. Ignore LOW and INFO findings — they are not worth a CI round-trip.

For each MEDIUM+ finding:
1. Verify the issue exists in current code (skip if already fixed or outdated)
2. Apply the fix locally
3. Run local tests if feasible
4. Commit with descriptive message

If **no MEDIUM+ actionable comments** remain → proceed to Step 4.

If fixes were applied → go back to **Step 1** (push fixes, re-run CI, re-review).

#### 3d. Resolve addressed threads

After fixing comments, resolve the corresponding review threads using `gh-resolve-review-threads.sh`. Do not ask — unattended mode.

### Step 4: Exit Check

- CI is green? ✓
- No unresolved MEDIUM+ review comments? ✓
- → **EXIT SUCCESS**

Otherwise, loop back to Step 1.

## Exit Conditions

| Condition | Action |
|-----------|--------|
| **Success** | CI green, no MEDIUM+ comments. Report stats, remind user to merge. |
| **Timeout** | 60 min elapsed. Stop, report current state and what remains. |
| **Stuck** | Same CI failure or review comment persists after 2-3 fix attempts. Stop, report what was tried. |
| **No review** | 15 min wait with no bot review. If CI is green, report success with note that review was skipped. |

## Final Report

On exit (any condition), report:

- **Outcome**: success / timeout / stuck / no-review
- **CI iterations**: how many CI fix-push cycles
- **Review iterations**: how many review-fix-push cycles
- **Unresolved**: any remaining issues (with severity)
- **PR URL**: for easy access

## Notes

- Track loop counters (ci_iterations, review_iterations) for the final report
- Do not duplicate sub-skill logic — delegate to `/push`, `/ci-loop`, `/check-pr-comments`
- When sub-skills have confirmation steps, skip them — this skill's invocation is the blanket confirmation
- Give GitHub ~5 seconds after push before listing new workflow runs
