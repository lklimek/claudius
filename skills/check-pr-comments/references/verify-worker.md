# Verify-Only Worker Brief

Brief for the strong worker that runs step 3 when the coordinator delegates it. Add the `delegate` § Agent Prompt Requirements (scope, skills, reporting channel); this file adds only what is specific to comment verification.

## Constraints

- Work in a fresh detached worktree at the PR head SHA (`grand-admiral` § Worktree Isolation naming); remove it before reporting.
- Verify only: never edit code, commit, reply, resolve, or post anything.
- Judge every comment against the **current** head — a bot may have reviewed an older one.
- Apply SKILL.md step 3 in full: review-body items get their own rows, duplicates merge into one ID, and earlier user decisions (reply chain or the coordinator's brief) change what each item needs.

## Report contract

Send one block per ID to the coordinator (`SendMessage`):

- Thread node ID (`PRRT_*`) and the first comment's `databaseId`; review-body items give the review/comment URL instead.
- Category slug (SKILL.md step 4 catalog).
- Verdict: valid / partly valid / invalid, with `file:line` evidence at the current head.
- Pre-existing on the base branch: yes / no.
- Architectural root cause: `no`, or the broader flaw with evidence and its other symptoms.
- Scope per the necessity gate, with its evidence.
- Blocker gates tripped, or none.
- Fix sketch and size: XS / S / M with an estimated line count.
- Handled elsewhere: open PRs, issues, upstream, or `—`.
- Effect of earlier user decisions on this item, if any.
- Ready reply text in English ending with the `git-and-github` attribution footer. When the disposition is the user's call, two replies: one for fix (marked "post only after the fix lands") and one for decline.
