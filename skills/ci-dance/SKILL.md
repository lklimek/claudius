---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
argument-hint: "timeout=300"
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh run *), Bash(git *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(*gh-resolve-review-threads.sh *), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment
---

# CI Dance — Unattended PR Pipeline

Fully autonomous loop: push, run three parallel streams (CI, grumpy-review, copilot review) each following trigger-wait-collect, merge findings, fix MEDIUM+ issues, repeat. No confirmations, no user interaction until done or stuck.

## Prerequisites

- Load `claudius:git-and-github` skill first
- Working tree has changes to push, or commits already pushed to a remote branch
- Remote is configured and CI workflows exist

## Unattended Mode

- **No confirmations** — invocation implies full consent to push, fix, and re-push
- **Override sub-skill confirmations** — when invoking `/push`, `/grumpy-review`, or `/check-pr-comments`, skip their "ask user" steps. This skill's invocation is the confirmation
- **Push freely** — commit and push fixes without asking
- **NEVER merge** — merging is always the user's responsibility

## Timeout

Parse `$ARGUMENTS` for `timeout=N` (minutes). Default: **300 minutes**. Record `start_time` at invocation. Before each loop iteration, check elapsed time — hard stop on timeout.

## Main Loop

```
LOOP (until exit condition):
  1. PUSH           — /push: commit, push, create/update PR
  2. THREE STREAMS  — run in parallel, each: trigger → wait → collect & classify
     ├── CI Stream
     ├── Grumpy Stream
     └── Review Stream
  3. MERGE          — combine classified findings from all streams, deduplicate
  4. FIX            — apply valid MEDIUM+ fixes, commit
  5. RESOLVE        — resolve addressed bot review threads
  6. EXIT CHECK     — no fixes applied AND CI green AND no MEDIUM+ findings → SUCCESS
```

### Step 1: Push

Invoke `/push` to commit staged/unstaged changes, push, and create or update the PR. Skip user confirmation per unattended mode.

If nothing to commit or push, proceed to Step 2.

### Step 2: Three Parallel Streams

All three streams run concurrently. Each follows the same lifecycle: **trigger (if needed) → wait → collect & classify findings**.

#### CI Stream

1. **Trigger**: CI runs automatically on push. Nothing to do.
2. **Wait**: Watch runs using the Watch and Collect procedure (see below). Do NOT fix.
3. **Collect & Classify**: For each failed run, diagnose from logs. Record as findings with severity, location, description. Verify each finding exists in current code.

#### Grumpy Stream

1. **Trigger**: Invoke `/grumpy-review` locally (forked context, produces severity-ranked JSON report).
2. **Wait**: Grumpy-review runs locally and completes.
3. **Collect & Classify**: Read the grumpy-review JSON report. Each finding already has severity. Verify findings exist in current code, discard outdated/false positives.

#### Review Stream

1. **Trigger**: Request copilot review: `gh pr edit --add-reviewer @copilot || true`
2. **Wait**: Poll for new reviews using `gh-fetch-reviews.sh`. Compare review IDs to detect new ones.
   - Poll interval: 30 seconds
   - Minimum wait: 5 minutes
   - Maximum wait: 20 minutes — proceed without if no review appears
   - Also check for any OTHER reviews (human or bot) that may have been added since last iteration
3. **Collect & Classify**: Fetch all review comments via `/check-pr-comments` (skip confirmations). Classify each: verify issue exists in current code, rate severity, check for false positives. Only flag MEDIUM (3)+ for action.

### Step 3: Merge

After all three streams complete:

1. Combine all classified findings into a unified list
2. Deduplicate — findings pointing to the same code location or describing the same issue
3. Present unified severity-ranked findings list

### Step 4: Fix

For each valid MEDIUM+ finding from the merged list:
1. Apply the fix locally
2. Run local tests if feasible
3. Commit with descriptive message

If no actionable findings, proceed to Step 5.

### Step 5: Resolve Threads

Resolve addressed bot review threads using `gh-resolve-review-threads.sh`. Bot threads only, per existing convention. Do not ask — unattended mode.

### Step 6: Exit Check

- No fixes applied this iteration AND CI was green AND no unresolved MEDIUM+ findings? -> **EXIT SUCCESS**
- Otherwise -> go to **Step 1** (push fixes, re-run everything)

## Watch and Collect (CI Sub-Procedure)

Sub-procedure of the CI Stream. Watch GitHub Actions runs and collect failures as findings. Do NOT fix or push here — findings flow back to the CI Stream's collect phase.

Do **not** start watching until all local fixes are pushed. Watching a superseded run wastes time.

### Run Ordering

When a push triggers multiple workflow runs, watch **sequentially starting with the fastest**. Check historical durations:
```bash
gh run list --workflow <workflow>.yml --status success --limit 50
```

### Procedure

1. **List runs** for the current branch:
   ```bash
   gh run list --branch "$(git branch --show-current)" --limit 10
   ```
   Identify runs triggered by the latest push. Order by expected duration (shortest first).

2. **Watch** each run sequentially:
   ```bash
   gh run watch {run_id} --exit-status
   ```
   - Succeeds -> next run. All succeed -> CI green, no findings.
   - Fails -> fetch failure logs (step 3). Continue watching remaining runs.

3. **Diagnose** failures and record as findings:
   ```bash
   gh run view {run_id} --log-failed
   ```
   Identify root cause: test failures, lint/format errors, dependency issues, environment problems. Record each as a finding (severity, file/location, description).

4. Return all CI findings to the CI Stream.

### CI Exit Conditions

- **Green**: all runs pass — no CI findings.
- **Flaky**: passes locally, fails in CI non-deterministically — record as finding, note flakiness.
- **Undiagnosable**: can't determine root cause from logs — record as finding with relevant log output.

## Exit Conditions

| Condition | Action |
|-----------|--------|
| **Success** | CI green, no MEDIUM+ findings. Report stats, remind user to merge. |
| **Timeout** | Time limit elapsed. Stop, report current state and what remains. |
| **Stuck** | Same failure or finding persists after 2-3 fix attempts. Stop, report what was tried. |
| **No review** | 20 min wait with no bot review. If CI is green, report success noting review was skipped. |

## Final Report

On exit (any condition), report:

- **Outcome**: success / timeout / stuck / no-review
- **CI iterations**: how many CI fix-push cycles
- **Review iterations**: how many review-fix-push cycles
- **Findings**: total found, fixed, skipped (with severity breakdown)
- **Unresolved**: any remaining issues (with severity)
- **PR URL**: for easy access

## Notes

- Track loop counters (ci_iterations, review_iterations, findings_fixed, findings_skipped) for the final report
- Do not duplicate sub-skill logic — delegate to `/push`, `/grumpy-review`, `/check-pr-comments`
- When sub-skills have confirmation steps, skip them — this skill's invocation is the blanket confirmation
- Give GitHub ~5 seconds after push before listing new workflow runs
- **Not for GitHub Actions** — this skill pushes commits that trigger CI, so running it inside a workflow causes concurrency cancellation loops. Use from CLI only.
