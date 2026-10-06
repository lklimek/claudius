---
name: check-pr-comments
description: "Fetches a PR's review comments, verifies each against the current code, summarizes the status, and replies to or resolves threads. This skill should be used when the user asks to \"check PR comments\", \"verify review comments are addressed\", or otherwise confirm that PR feedback is resolved in code. It can optionally produce a triage-compatible report."
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr view *), Bash(gh pr comment *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-review-comments.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-list-review-threads.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(ghsudo ${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-post-review-reply.sh *), Bash(gh search code *)
---

# Check PR Comments Workflow

Workflow for checking/triaging/verifying existing PR review comments.

## 1. Fetch All Comments

**ALWAYS fetch fresh comments on every invocation** — never assume none are new. Script usage and output shapes: `git-and-github` [pr-review.md](../git-and-github/references/pr-review.md).

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/gh-list-review-threads.sh <owner/repo> <pr>     # review threads + isResolved
${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-review-comments.sh <owner/repo> <pr>   # inline comments (path, line, body, html_url)
${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh <owner/repo> <pr>           # review summaries
gh pr view <pr> -R <owner/repo> --json comments     # PR-level comments
```

Carry `isResolved` forward per thread — step 3 skips already-resolved ones. The wrappers paginate to the end.

## 2. Checkout and Pull the PR Branch

Skip when `git rev-parse HEAD` already equals the PR head (e.g. a CI checkout). Otherwise run `gh pr checkout <number>`, then `git pull --ff-only` — deliberately not pre-approved (they rewrite the working tree, and a `git pull *` grant would admit `--upload-pack=<cmd>`), so each prompts for approval.

## 3. Verify Each Comment Against Current Code

**Trust GitHub's resolved status — do not re-verify already-resolved threads.** Classify any thread fetched with `isResolved: true` as **Resolved** and skip the rest of this section for it: no re-reading code, no call-tree walk, no second-guessing a prior resolution. Verify only `isResolved: false` threads.

For every unresolved inline comment, read the code at the referenced location (applying `coding-best-practices` Cross-Cutting Rules to the change) and **verify the identified issue is actually fixed** — not just that the code changed:

- **Verify state before resolving — broad instructions are not authorization** (`coding-best-practices` "Verify facts before acting on broad instructions"). Never mark a thread resolved on a blanket "just resolve everything" or a commit message that *claims* a fix; unverifiable against current code → `Unresolved` with an explicit "needs verification" recommendation. Governs threads resolved this session only — never reopens threads already resolved on GitHub.
- Semantic satisfaction, not syntactic; every sub-item independently — resolved only when **all** are addressed; the intended end-user/developer experience, not just technical correctness.
- **Call-tree walk on touched functions**: if the comment references a function whose body or signature changed in the resolution commits (`git diff <RESOLUTION_BASE>...HEAD -- <file>`), run [../grumpy-review/references/call-tree-walk.md](../grumpy-review/references/call-tree-walk.md) first — a caller still depending on the old contract turns "fixed" into Unresolved with a CALL-tagged follow-up.

**Author classification**: **Bot** — username ends with `[bot]` (e.g. `dependabot[bot]`) or the API returns `type: "Bot"`; **Human** — all others.

## 4. Present Summary

Present concisely to the user:

- Total comments checked, resolved vs unresolved
- Per comment, Claude's assessment:
  - **Already resolved** (`isResolved: true` at fetch): report as resolved citing GitHub's status — do not restate a fix assessment you didn't perform (step 3).
  - **Resolved by verification this session**: confirm the fix is adequate, or flag concerns when technically present but semantically incomplete. State whether the original comment was valid.
  - **Unresolved**: your recommendation (priority, suggested approach). If you disagree with the reviewer's concern, say so with a brief reason.
- Unresolved first, then resolved
- Author type (bot/human) and planned action (auto-resolve, reply, etc.) per comment

Default end of workflow, except step 8 (resolve threads).

---

## Optional: Structured Report (on request only)

Steps 5-7 run only on explicit request (e.g. "generate report", "with report"). Step 8 applies to both flows.

## 5. Build Structured Report JSON

Read [references/structured-report.md](references/structured-report.md) for the `report.json` shape, finding format, title/permalink/scoring rules. Recipe pinned here:

- **Resolved** comments: `likelihood=0.0, impact=0.0, relevance=0.0` — the Informational floor (`claudius:severity` § 3), `verdict: "RESOLVED"`. `recommendation` describes what was done — for threads trusted via `isResolved: true` (step 3), say it was already resolved on GitHub rather than inventing an unverified fix. The coordinator derives `severity = 1` (INFO).

## 6. Validate Report

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 7. Render and Present

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py report.json --format md
```

Present the rendered markdown (optionally `--format html`). The user can also run `triage-findings report.json` for interactive triage of unresolved comments.

## 8. Resolve and Reply to Threads

**Sequencing gate — decide fix/no-fix before acting.** Do not reply to or resolve an `Unresolved` (step 3) comment while its fix is still pending in this pass. Settle each comment's disposition — `Fixed (verified this session)` or `Not fixed` — then apply the matching matrix row. Replying during triage and fixing later leaves a redundant reply on every fixed thread; a fixed bot thread goes straight to auto-resolve with no intermediate reply.

Apply the matrix **without asking for confirmation**, except where noted:

| Author | Status | Action |
|--------|--------|--------|
| Any | Already resolved (`isResolved: true`) | No action — do not reply or resolve again |
| Bot | Fixed (verified this session) | Auto-resolve the thread (no confirmation needed) |
| Bot | Not fixed | Post a reply explaining what remains. Do NOT resolve. |
| Human | Fixed (verified this session) | Post a reply explaining what was done. Do NOT resolve. |
| Human | Not fixed | Post a reply explaining what remains. Do NOT resolve. |

**NEVER auto-resolve human-created threads** without explicit per-invocation permission (e.g. "resolve all fixed threads", "resolve human threads too"). Even when fully fixed, the human reviewer resolves their own threads.

**Posting replies:**
- Inline thread replies: `${CLAUDE_PLUGIN_ROOT}/scripts/gh-post-review-reply.sh <owner/repo> <pr> <comment_id> <body_file>` — `comment_id` = databaseId of the thread's first comment; body read from a Markdown file (no inline form); retries once via `ghsudo` on 403; outputs the reply's html_url
- PR-level replies: `gh pr comment <pr> -R <owner/repo> --body-file <file>`
- Keep replies concise: what was done, what remains, relevant commit reference

**Resolving bot threads** (fixed only) via the wrapper script (see `git-and-github` safety rule #10 for sandbox requirements):

```bash
# GraphQL node IDs (PRRT_*) — pass directly:
${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh <PRRT_id> [PRRT_id ...]

# REST IDs (discussion_r* or numeric databaseId) — use enhanced mode:
${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh <owner/repo> <pr_number> --id discussion_r123 --id 456 [...]
```

The wrapper uses a GraphQL mutation directly. The `--id` form auto-converts `discussion_r*`/numeric IDs to thread node IDs; mix freely with `PRRT_*` in one invocation. Never resolve partially-addressed threads.

With a triage-role token, wrap the entire script invocation in `ghsudo` per the standing fallback convention; ambient bot auth commonly returns 403 for `ResolveReviewThread`.
