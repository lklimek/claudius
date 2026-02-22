---
name: ci-loop
description: Autonomous CI monitoring and fix loop — wait for workflow run to complete, read failure logs, fix issues, push, and repeat until CI is green.
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh run list *), Bash(gh run view *), Bash(gh run watch *), Bash(git add *), Bash(git commit *), Bash(git push), Bash(git push origin *), Bash(git push -u origin *), Bash(git branch *), Bash(git diff *), Bash(git log *), Bash(git status *)
---

# CI Monitoring and Fix Loop

Autonomous loop for monitoring GitHub Actions CI and fixing failures. Repeats until the workflow passes.

## User Confirmation

**Before starting the loop**, present the user with a summary of what this skill will do (monitor CI, read failure logs, apply fixes, commit, and push — potentially multiple iterations) and ask for explicit permission to proceed. Do not begin monitoring or making changes until the user confirms.

## Prerequisites

- Changes are pushed to a branch with a CI workflow configured
- The workflow has been triggered (by push or other event)

## Important

Do **not** start monitoring a workflow run until all local fixes are pushed. Watching a run that will be superseded by a new push wastes time.

## Monitoring Strategy

When a push triggers **multiple workflow runs**, monitor them **sequentially**, starting from the workflow that historically completes fastest. To determine order, check recent successful runs for each workflow:

```bash
# Check typical duration for a specific workflow (use workflow filename)
gh run list --workflow <workflow>.yml --status success --limit 50
```

Use `gh run watch` to wait for each run — do **not** poll `gh run view` or `gh run list` in a loop. `gh run watch` streams status updates and exits when the run finishes.

## Loop Steps

### 1. Find the latest workflow runs

```bash
# List recent runs for the current branch
gh run list --branch "$(git branch --show-current)" --limit 10
```

Identify all runs triggered by the latest push. Order them by expected duration (shortest first) based on historical data. Start watching the fastest workflow first.

### 2. Wait for a run to complete

Select the shortest run that was not yet checked and monitor it.

```bash
# Watch the run until it finishes (exits non-zero on failure)
gh run watch {run_id} --exit-status
```

- If the run **succeeds** → move to the next workflow run in the sequence.
- If the run **fails** → proceed to Step 3 immediately (no need to wait for remaining runs).
- If **all runs succeed** → exit the loop successfully. Proceed to **Step 7**.

### 3. Read failure logs

```bash
# Fetch logs for failed jobs only
gh run view {run_id} --log-failed
```

Parse the output to identify:
- Which job(s) failed
- The specific error messages or test failures
- Whether the failure is in application code, tests, configuration, or dependencies

### 4. Diagnose and fix

- Identify the root cause from the logs.
- Apply the fix locally.
- Run the test suite locally to verify the fix before pushing.

Common CI failure categories:
- **Test failures** — fix the failing test or the code it tests
- **Lint/format errors** — run the project's linter/formatter
- **Dependency issues** — update requirements, lock files, or install commands
- **Environment issues** — missing env vars, wrong Python/Node version, missing system deps

### 5. Commit changes

Create individual commit for each fixed issue.

```bash
git add <changed-files>
git commit -m "<type>: <what was fixed>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### 6. Check remaining runs

Go to **Step 2** to monitor next run.

### 7. Push the fixes

Push all fixes in a bulk

```bash
git push
```

### 8. Monitor the new run

Go back to **Step 1** — a new run will be triggered by the push.

## Exit conditions

- **Success**: The latest workflow run passes (green).
- **Stuck**: The same failure persists after 2-3 fix attempts — inform the user with a summary of what was tried.
- **Error**: Cannot diagnose the failure from logs alone — inform the user with the relevant log output.

## Notes

- Always run tests locally before pushing a fix to avoid unnecessary CI round-trips.
- If CI fails due to flaky tests (passes locally, fails in CI non-deterministically), note this to the user rather than retrying blindly.
- If the CI configuration itself needs changes (e.g., missing `pip install` for a new dependency), fix the workflow file and explain the change.
- Do not start watching a new run immediately after pushing — give GitHub a few seconds to queue the workflow before listing runs.
