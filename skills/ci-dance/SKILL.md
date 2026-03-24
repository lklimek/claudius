---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
argument-hint: "timeout=300"
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh run *), Bash(git *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(*gh-resolve-review-threads.sh *), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment
---

# CI Dance — Unattended PR Pipeline

Fully autonomous loop: push, run CI + copilot + grumpy-review in parallel, consolidate findings, fix MEDIUM+ issues, repeat. No confirmations, no user interaction until done or stuck.

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
  1. PUSH         — /push: commit, push, create/update PR
  2. PARALLEL     — start all three concurrently:
     a. CI        — runs automatically (triggered by push)
     b. Copilot   — gh pr edit --add-reviewer @copilot || true
     c. Grumpy    — invoke /grumpy-review locally
  3. WAIT         — wait for ALL three to complete:
     a. Grumpy    — finishes first (local)
     b. CI        — watch runs until done (DO NOT fix yet)
     c. Copilot   — poll for review (5–20 min window)
  4. CONSOLIDATE  — merge findings from all three sources
  5. CLASSIFY     — validate each finding, rate severity
  6. FIX          — apply valid MEDIUM+ fixes, commit
  7. RESOLVE      — resolve addressed bot review threads
  8. EXIT CHECK   — no fixes applied AND CI was green AND no unresolved MEDIUM+ findings → SUCCESS, else → Step 1
```

### Step 1: Push

Invoke `/push` to commit staged/unstaged changes, push, and create or update the PR. Skip user confirmation per unattended mode.

If nothing to commit or push, proceed to Step 2.

### Step 2: Parallel Review Start

Kick off all three review sources concurrently:

**a. CI** — triggered automatically by the push. Do nothing yet.

**b. Copilot** — request review:
```bash
gh pr edit --add-reviewer @copilot || true
```

**c. Grumpy Review** — invoke `/grumpy-review` locally. This runs in the current session as a forked context and produces a consolidated severity-ranked JSON report.

### Step 3: Wait for Results

**a. Grumpy** — finishes first (local). Collect the severity-ranked JSON report.

**b. CI** — watch runs using the CI Monitoring procedure below. Collect failure information as findings. Do NOT fix or push during this step.

**c. Copilot** — poll for new reviews using `gh-fetch-reviews.sh`. Compare review IDs to detect new reviews.
- Poll interval: 30 seconds
- Minimum wait: 5 minutes (copilot is typically fast)
- Maximum wait: 20 minutes — if no review appears, proceed without it

Check timeout before each wait cycle.

### Step 4: Consolidate

Merge findings from all three sources into a unified list:

1. **Grumpy-review findings** — from the local JSON report
2. **Copilot review comments** — fetch via `/check-pr-comments` (Steps 1-3, skip confirmations)
3. **CI failure findings** — diagnosed failure logs collected during CI monitoring

Deduplicate findings that point to the same code location or describe the same issue.

### Step 5: Classify

For each finding in the consolidated list:

1. **Verify** — check the issue exists in current code (skip if already fixed or outdated)
2. **Validate** — confirm the finding is real (false positives exist, especially from automated reviewers)
3. **Rate severity** — only act on **MEDIUM (3) or above**. Skip LOW and INFO — not worth a CI round-trip.

### Step 6: Fix

For each valid MEDIUM+ finding:
1. Apply the fix locally
2. Run local tests if feasible
3. Commit with descriptive message

If no actionable findings remain, proceed to Step 7.

### Step 7: Resolve Threads

Resolve addressed bot review threads using `gh-resolve-review-threads.sh`. Bot threads only, per existing convention. Do not ask — unattended mode.

### Step 8: Exit Check

- No fixes applied this iteration AND CI was green AND no unresolved MEDIUM+ findings? -> **EXIT SUCCESS**
- Otherwise -> go to **Step 1** (fixes need pushing, or CI needs another run)

## CI Monitoring

Watch GitHub Actions runs and collect failures as findings. Used in Step 3b. Do NOT fix or push here — findings flow into the consolidation phase.

Do **not** start monitoring until all local fixes are pushed. Watching a superseded run wastes time.

### Run ordering

When a push triggers multiple workflow runs, monitor **sequentially starting with the fastest**. Check historical durations:
```bash
gh run list --workflow <workflow>.yml --status success --limit 50
```

### Watch and Collect

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
   Identify root cause: test failures, lint/format errors, dependency issues, environment problems. Record each as a finding (severity, file/location, description) for the consolidation phase.

4. Return all CI findings to Step 4: Consolidate.

### CI exit conditions

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
