---
name: check-pr-comments
description: "Fetches a PR's review comments, verifies each against the current code, presents a per-comment decision table, and — after the user's decisions or in fix mode — fixes, replies to, or resolves threads. This skill should be used when the user asks to \"check PR comments\", \"verify review comments are addressed\", or otherwise confirm that PR feedback is resolved in code. It can optionally produce a triage-compatible report."
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr view *), Bash(gh pr comment *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-review-comments.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-list-review-threads.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(ghsudo ${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-post-review-reply.sh *), Bash(gh search code *), Bash(gh search prs *), Bash(gh search issues *), Bash(gh pr list *), Bash(git for-each-ref *), Bash(git worktree list *)
---

# Check PR Comments Workflow

Workflow for checking/triaging/verifying existing PR review comments.

On Codex/other hosts, resolve commands from the installed absolute script paths in `allowed-tools`, or locate the plugin tree containing `scripts/` and `schemas/` (Codex commonly `~/.codex/claudius`). Resolve relative references from the loaded skill; never pass unresolved Claude placeholders to a shell.

## 0. Choose Mode

Ask once per invocation (AskUserQuestion; elsewhere a plain question):

- **Table, then wait** (default, recommended): analyse everything, show the step 4 table, change nothing — no code, replies, or resolves — until the user decides per ID (step 8).
- **Fix without asking**: fix each Unresolved, in-scope comment that verification judged valid, per `coding-best-practices` (its independent-review threshold applies to the total diff); verify, commit, and push per `git-and-github`. Out-of-scope, disputed, and handled-elsewhere (step 3) comments get no fix. Then apply the step 8 matrix and show the step 4 table.

Skip the question when this request, a standing user/project instruction, or the invoking skill already sets the mode. No preset mode and no reachable user (CI, headless, a subagent without a user channel) → Table, then wait, ending after the table. State the mode in one line.

## 1. Fetch All Comments

**ALWAYS fetch fresh comments on every invocation** — never assume none are new. Script usage and output shapes: `git-and-github` [pr-review.md](../git-and-github/references/pr-review.md).

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/gh-list-review-threads.sh <owner/repo> <pr>     # review threads + isResolved
${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-review-comments.sh <owner/repo> <pr>   # inline comments (path, line, body, html_url)
${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh <owner/repo> <pr>           # review summaries
gh pr view <pr> -R <owner/repo> --json comments     # PR-level comments
```

All four are mandatory — review bodies and PR comments can carry requests with no inline thread. Carry `isResolved` forward per thread — step 3 skips already-resolved ones in chat-only checks; report/table-file checks assess them independently. The wrappers paginate to the end.

## 2. Checkout and Pull the PR Branch

Skip when `git rev-parse HEAD` already equals the PR head (e.g. a CI checkout). Otherwise run `gh pr checkout <number>`, then `git pull --ff-only` — deliberately not pre-approved (they rewrite the working tree, and a `git pull *` grant would admit `--upload-pack=<cmd>`), so each prompts for approval.

## 3. Verify Each Comment Against Current Code

Apply [delegate](../delegate/SKILL.md) § Independent Verification to the review comments.

**Chat-only checks trust GitHub's resolved status:** classify `isResolved: true` threads as **Resolved** and skip verification. For a requested report/table file, assess their current code too, keeping GitHub `thread_state` independent from the assessment per `report-format`. Never reopen or re-resolve an already-resolved thread automatically.

For every unresolved inline comment and review-body/PR-comment item (below), read the code at the referenced location (applying `coding-best-practices` Cross-Cutting Rules to the change) and **verify the identified issue is actually fixed** — not just that the code changed:

- **Verify state before resolving — broad instructions are not authorization** (`coding-best-practices` "Verify facts before acting on broad instructions"). Never mark a thread resolved on a blanket "just resolve everything" or a commit message that *claims* a fix; unverifiable against current code → `Unresolved` with an explicit "needs verification" recommendation. Governs threads resolved this session only — never reopens threads already resolved on GitHub.
- Semantic satisfaction, not syntactic; every sub-item independently — resolved only when **all** are addressed; the intended end-user/developer experience, not just technical correctness.
- **Trace touched functions**: for functions added, removed, or changed in the resolution commits (body or signature), apply [execution-paths.md](../review-changes/references/execution-paths.md) to the comment's affected scope. Check every affected call site; a caller still depending on the old contract turns "fixed" into Unresolved with a CALL-tagged follow-up. Unresolved coverage must be reported, not treated as proof of a fix.

**Review-body and PR-comment items** — first-class rows, never only context. Split into itemised requests the non-empty bodies of: every `CHANGES_REQUESTED` review not superseded by a later `APPROVED` from its author; each human author's latest review; human PR-level comments; bot bodies only for findings with no matching thread. Each item gets its own ID and is verified like an unresolved thread. With no `isResolved`, an item is **Resolved** only when verified fixed in current code, or when a later reply in the PR by its author or a maintainer explicitly withdraws or settles it.

**Pre-analysis** — for every unresolved thread and every unresolved review-body/PR-comment item:

- **Handled elsewhere?** Search shallowly (`--limit 10`) by keywords and paths: local branches and worktrees (`git for-each-ref`, `git worktree list`; uncommitted WIP via `git -C <worktree> status --short`, deliberately ungranted — a `git -C *` rule would also admit `-c <config>`), stacked/child and other open PRs (`gh pr list`, `gh search prs`), issues (`gh search issues`). Cite `#N`, `branch@SHA`, or `uncommitted WIP in <worktree>`.
- **Earlier decisions**: honour decisions in the reply chain (e.g. "moved to #N", "deferred by maintainer").
- **Duplicates**: merge threads and items about one problem into one ID, keeping every thread ID and source link.

**Scope**: Read `${CLAUDE_PLUGIN_ROOT}/skills/severity/SKILL.md` § 5 (skip if loaded) and classify every `Unresolved` comment **in scope** or **out of scope** per its PR scope. A reviewer's request is not PR intent until the user or a human PR author accepts it; an out-of-scope comment is not fixed in this PR.

**Author classification**: **Bot** — username ends with `[bot]` (e.g. `dependabot[bot]`), the API returns `type: "Bot"`, or the project instructions name the account as a review bot (some run under ordinary user accounts); **Human** — all others.

## 4. Decision Table

Both modes end with this table (fix mode: after step 8). Above it, one line: `PR #N: <one sentence on what the PR is for, from its title/TL;DR>`.

IDs are the report IDs (`CMT-001`, …, ordered per [structured-report.md](references/structured-report.md) § Finding additions, rough severity standing in for floats when no report exists) and are fixed once shown: a later report and `triage-findings` reuse them, never re-sort. A requested report (steps 5-7) is built before the table; in fix mode, after step 8. Keep cells ≤ ~15 words:

| ID | Source | Problem | Scope | Elsewhere | Opinion | Recommendation |
|----|--------|---------|-------|-----------|---------|----------------|

- **Source**: `thread` / `review-body` / `PR comment`.
- **Problem**: plain language, concrete impact (who is hurt, how).
- **Scope**: `in`/`out` (step 3) plus a short reason citing the PR's stated goal; if another PR fits better, `#M: <its scope>`.
- **Elsewhere**: pre-analysis hit, or `—`.
- **Opinion**: valid or not, rough severity, disagreement with the reviewer, `bot`/`human`; flag a tripped G-FUNDS/G-SECRET/G-CRYPTO/G-DATA.
- **Recommendation**: `resolve: fixed in <sha>` (verified this session) / `fix here` / `reject: <reason>` / `follow-up PR` (new, or `#M`) / `TODO` / `handled in #N`. Fix mode: the action taken.

Below the table: one line per merged ID listing its thread/source links. Chat-only checks summarize threads resolved at fetch and items settled by a reply as `Resolved: N (CMT-…)` instead of rows. Report/table-file checks retain their assessment rows, including any remaining concern in a resolved thread. Table mode ends the turn with "Decisions per ID?".

A user decision rejecting or re-rating a comment as unimportant (or more important) at project scale is a calibration example: save it per `${CLAUDE_PLUGIN_ROOT}/skills/severity/references/system-rating.md` § Calibration memory.

---

## Optional: Structured Report (on request only)

Steps 5-7 run on an explicit report request or a request to save the comment table as a file. Ordinary tables stay in chat. File output defaults to one self-contained HTML; explicit format/layout requests win. Load `report-format` and its [comment assessment contract](../report-format/references/comment-assessments.md). Step 8 applies to both flows; file generation itself authorizes no GitHub actions.

## 5. Build Structured Report JSON

The report has the same structure as a `review-changes` report — one definition, not a parallel one: finding shape per the `report-format` skill (load it), envelope per its [coordinator-envelope.md](../report-format/references/coordinator-envelope.md). Floats and `merge_class` are this skill's to assign, so first Read `${CLAUDE_PLUGIN_ROOT}/skills/severity/SKILL.md` and `${CLAUDE_PLUGIN_ROOT}/skills/severity/references/merge-classification.md` (skip what this session already loaded). [references/structured-report.md](references/structured-report.md) lists only what a comment check adds (comment fields, title, permalink and scoring rules). Recipe pinned here:

- Build `comment_assessments` for requests and relevant replies/status messages. Verify before assigning `already_fixed`; GitHub resolution alone does not prove a fix. Actual remaining defects go into scored `findings`, linked by `finding_id`; keep assessment and thread state separate. Record proposals before step 8; set `action_taken` only after execution. For already tracked topics, the proposed reply contains only the public PR/issue URL.

## 6. Validate Report

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 7. Render and Present

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py report.json --format html
```

Link the HTML file. Generate Markdown/CSV/PDF only when requested. The user can also run `triage-findings report.json` for interactive triage of scored concerns; unscored context rows remain visible as evidence.

## 8. Resolve and Reply to Threads

**Gate threads**: a thread whose concern trips G-FUNDS, G-SECRET, G-CRYPTO, or G-DATA is resolved only when that ID's user decision explicitly says resolve — never by the matrix.

### Fix mode

**Sequencing gate — decide fix/no-fix/out-of-scope before acting.** Do not reply to or resolve an `Unresolved` (step 3) comment while its fix is still pending in this pass. Settle each comment's disposition — `Fixed (verified this session)`, `Not fixed`, `Disputed`, `Handled elsewhere`, or `Out of scope` — then apply the matching matrix row. Replying during triage and fixing later leaves a redundant reply on every fixed thread; a fixed bot thread goes straight to auto-resolve with no intermediate reply.

Apply the matrix **without asking for confirmation**:

| Author | Status | Action |
|--------|--------|--------|
| Any | Already resolved (`isResolved: true`) | No action — do not reply or resolve again |
| Bot | Fixed (verified this session) | Auto-resolve the thread |
| Bot | Not fixed | Post a reply explaining what remains. Do NOT resolve. |
| Bot | Out of scope | Reply "Out of scope for this PR; reported to the maintainer", then resolve. |
| Bot | Disputed | Reply with the reason, then resolve. |
| Bot | Handled elsewhere (public `#N`) | Reply "Addressed in #N.", then resolve. |
| Human | Fixed (verified this session) | Post a reply explaining what was done. Do NOT resolve. |
| Human | Not fixed | Post a reply explaining what remains. Do NOT resolve. |
| Human | Disputed | Reply with the reason. Do NOT resolve. |
| Human | Handled elsewhere (public `#N`) | Reply "Addressed in #N." Do NOT resolve. |
| Any | Handled elsewhere (local branch/WIP only) | No reply, no resolve — local state stays off GitHub; the table reports it. |
| Human | Out of scope | No reply, no resolve — the table proposes a disposition; the user may accept it into PR intent, which makes it in scope. |

**NEVER auto-resolve human-created threads** without explicit per-invocation permission (e.g. "resolve all fixed threads", "resolve human threads too"). Even when fully fixed, the human reviewer resolves their own threads.

### Table mode — after the user's per-ID decisions

Apply each decision exactly; never extend it to IDs the user did not name. A per-ID decision is the per-invocation permission above: every "resolve" below covers human threads too. Reply and resolve on every thread of a merged ID.

| Decision | Action |
|----------|--------|
| `resolve` | Verified fixed: bot → resolve; human → reply what was done, then resolve. |
| `fix here` | Fix, verify, commit, and push per `git-and-github`, then the matrix's Fixed row. |
| `handled in #N` | Reply "Per maintainer decision, this is addressed in #N, which we treat as sufficient for #<this PR>.", then resolve. |
| `follow-up PR` | Existing `#M`: reply with its link, then resolve. New: first create a draft skeleton per `git-and-github` § Commit, Push, PR Workflow (base: the default branch, unless the follow-up needs code from an open PR — then stack on that PR; empty commit; plain-language body linking the threads), reply with its link, and resolve now — do not wait for the implementation. |
| `TODO` | Save it with `memcan:todo` (project = repo name), linking the threads. Reply "Per maintainer decision, out of scope for this PR." — never mention the TODO or its tracker (private, local) — then resolve. Save failed or `memcan:todo` unavailable → no reply, no resolve; report the item to the user. |
| `reject` | Reply with the maintainer's reason. Resolve bot threads; leave human threads open unless the decision says resolve (e.g. "CMT-002 reject, resolve"). |

Create GitHub issues only when the user asks.

**Review-body and PR-comment items** follow the same matrix and decisions, but have no thread to reply to or resolve: post one PR-level comment per source review/comment listing, per item, the reply text — or "done" where the row only resolves; omit no-reply items.

**Re-review gate**: never request or report a `CHANGES_REQUESTED` reviewer's re-review as due until every item of their latest such review, threads and body items alike, is Fixed (verified this session), Resolved, or closed by a user decision; otherwise list what remains.

**Posting replies:**
- Inline thread replies: `${CLAUDE_PLUGIN_ROOT}/scripts/gh-post-review-reply.sh <owner/repo> <pr> <comment_id> <body_file>` — `comment_id` = databaseId of the thread's first comment; body read from a Markdown file (no inline form); retries once via `ghsudo` on 403; outputs the reply's html_url
- PR-level replies: `gh pr comment <pr> -R <owner/repo> --body-file <file>`
- Keep replies concise: what was done, what remains, relevant commit reference

**Resolving threads** via the wrapper script (see `git-and-github` safety rule #10 for sandbox requirements):

```bash
# GraphQL node IDs (PRRT_*) — pass directly:
${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh <PRRT_id> [PRRT_id ...]

# REST IDs (discussion_r* or numeric databaseId) — use enhanced mode:
${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh <owner/repo> <pr_number> --id discussion_r123 --id 456 [...]
```

The wrapper uses a GraphQL mutation directly. The `--id` form auto-converts `discussion_r*`/numeric IDs to thread node IDs; mix freely with `PRRT_*` in one invocation. Never resolve partially-addressed threads.

With a triage-role token, wrap the entire script invocation in `ghsudo` per the standing fallback convention; ambient bot auth commonly returns 403 for `ResolveReviewThread`.
