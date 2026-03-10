---
name: review-loop
description: Use to autonomously handle peer review — request, wait, fix comments, push, repeat until resolved.
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(git *)
---

# Peer Review Loop

Autonomous loop for addressing peer review feedback on a pull request. Repeats until the reviewer has no new actionable comments.

## User Confirmation

**Before starting the loop**, present the user with a summary of what this skill will do (request review, wait for feedback, apply fixes, commit, push, and re-request — potentially multiple iterations) and ask for explicit permission to proceed. Do not begin the loop until the user confirms.

## Prerequisites

- A pull request already exists on GitHub
- Changes are pushed to the remote branch
- The reviewer is specified (default: `copilot`)

## Loop Steps

### 1. Request review

Request review from the specified reviewer. See the **github** skill (`PR Review Comments > Requesting reviewers` section) for the wrapper script.

### 2. Wait for review completion

Poll until a new review appears. Use the `gh-fetch-reviews.sh` wrapper from the **github** skill (`PR Review Comments` section). Reviews are ordered by `submitted_at`; compare against the last known review ID to detect new ones.

- Track the latest review ID before requesting. A new review has a higher ID.
- Timeout after ~10 minutes of polling — inform the user if no review arrives.

### 3. Read review comments

Fetch inline comments associated with the latest review. See the **github** skill (`PR Review Comments > Fetching inline review comments` section) for the wrapper script.

- Filter comments by the new review's ID to avoid re-processing stale comments from earlier reviews.
- Distinguish actionable comments (code suggestions, requested changes) from informational ones (praise, acknowledgments).

### 4. Evaluate comments

For each new comment:
- If the issue is **already fixed** in the current code (stale comment from before a force-push), skip it.
- If the comment is **not actionable** (e.g., "looks good", informational), skip it.
- If the comment identifies a **real issue**, fix it.

If **no actionable comments** remain → exit the loop successfully.

### 5. Fix issues

- Apply the necessary code changes.
- Run the project's test suite locally to verify fixes don't break anything.
- If the fix changes behavior described in the PR, update the PR description.

### 6. Push fixes

```bash
git add <changed-files>
git commit -m "<type>: address review feedback

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
git push
```

### 7. Re-request review

Go back to **Step 1** and repeat.

## Exit conditions

- **Success**: The latest review has no new actionable comments.
- **Timeout**: No new review appears within ~10 minutes of polling.
- **Error**: Push or test failure that cannot be resolved automatically — inform the user.

## Notes

- Always filter comments by review ID to avoid re-addressing already-fixed issues from prior review rounds.
- After force-pushes, old inline comments may appear on outdated diffs — verify against current code before acting.
- If the reviewer requests changes that conflict with the PR's intent, flag it to the user rather than making the change autonomously.
- Update the PR description if review feedback reveals missing context (e.g., unrelated fixes bundled into the PR).
