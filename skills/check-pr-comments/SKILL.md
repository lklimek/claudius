---
name: check-pr-comments
description: "This skill should be used when the user asks to \"check PR comments\", \"verify review comments are addressed\", or otherwise confirm that PR feedback is resolved in code. It can optionally produce a triage-compatible report."
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr checkout *), Bash(gh pr view *), Bash(git pull *), Bash(git fetch *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(*validate_report.py *), Bash(*generate_review_report.py *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-list-review-threads.sh *), Bash(*gh-resolve-review-threads.sh *), Bash(*gh-post-review-reply.sh *), Bash(which *), Bash(rg *), Bash(ctags *), Bash(global *), Bash(gtags *), Bash(tree-sitter *), Bash(gh search code*), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment, mcp__plugin_claudius_github__add_issue_comment
---

# Check PR Comments Workflow

Workflow for checking/triaging/verifying existing PR review comments.

## 1. Fetch All Comments

**ALWAYS fetch fresh comments on every invocation** — never assume none are new. Bare coordinator sessions typically lack `mcp__plugin_claudius_github__*` → [gh CLI fallback](references/gh-cli-fallback.md); agents whose frontmatter lists the tools prefer MCP.

Via `pull_request_read`: **review threads** `get_review_comments` (carry `isResolved` forward per thread — step 3 skips already-resolved ones), **review summaries** `get_reviews`, **PR-level comments** `get_comments`. Paginate to the end (`perPage` + `page`, or `perPage` + `after` cursor for review comments).

## 2. Checkout and Pull the PR Branch

```bash
gh pr checkout <number>
git pull
```

## 3. Verify Each Comment Against Current Code

**Trust GitHub's resolved status — do not re-verify already-resolved threads.** Classify any thread fetched with `isResolved: true` as **Resolved** and skip the rest of this section for it: no re-reading code, no call-tree walk, no second-guessing a prior resolution. Verify only `isResolved: false` threads.

For every unresolved inline comment, read the code at the referenced location and **verify the identified issue is actually fixed** — not just that the code changed:

- **Verify state before resolving — broad instructions are not authorization** (`coding-best-practices` "Verify facts before acting on broad instructions"). Never mark a thread resolved on a blanket "just resolve everything" or a commit message that *claims* a fix; unverifiable against current code → `Unresolved` with an explicit "needs verification" recommendation. Governs threads resolved this session only — never reopens threads already resolved on GitHub.
- Semantic satisfaction, not syntactic; every sub-item independently — resolved only when **all** are addressed; the intended end-user/developer experience, not just technical correctness.
- **Call-tree walk on touched functions**: if the comment references a function whose body or signature changed in the resolution commits (`git diff $RESOLUTION_BASE...HEAD -- <file>`), run [../grumpy-review/references/call-tree-walk.md](../grumpy-review/references/call-tree-walk.md) first — a caller still depending on the old contract turns "fixed" into Unresolved with a CALL-tagged follow-up.

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

Default end of workflow. Steps 5-7 (structured report) run only on explicit request (e.g. "generate report", "with report"). Step 8 (resolve threads) applies to both flows.

---

## Optional: Structured Report (on request only)

## 5. Build Structured Report JSON

Produce `report.json` per the unified report schema (`../../schemas/review-report.schema.json` v4.0.0; `3.x` accepted read-only for legacy reports, never for new output — this skill has no coordinator derive-pass to correct a stale version).

### Report structure

```json
{
  "schema_version": "4.0.0",
  "metadata": {
    "project": "<owner>/<repo>",
    "date": "YYYY-MM-DD",
    "branch": "<pr-branch>",
    "commit": "<full 40-char SHA from `git rev-parse @{u}` (fall back to `git rev-parse HEAD` when the branch has no upstream)>",
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

`metadata.commit` must be the full 40-character SHA when present (omit for non-git directories). Omit `metadata.repository` — no consumer of standalone comment-check reports needs it; permalinks (below) are built from `metadata.project`.

### Finding format

Each review comment becomes one finding:

```json
{
  "id": "CMT-001",
  "likelihood": 0.1,
  "impact": 0.1,
  "relevance": 0.5,
  "title": "Add fee-headroom guard to transfer_with_change_address",
  "location": "path/to/file.rs:42-56",
  "location_permalink": "https://github.com/<owner>/<repo>/blob/<commit>/path/to/file.rs#L42-L56",
  "description": "What the comment asked for (multi-line OK)",
  "recommendation": "What was done (RESOLVED) or what to do (UNRESOLVED)",
  "reviewer": "github-username",
  "author_type": "bot | human",
  "comment_id": 12345678,
  "comment_url": "https://github.com/<owner>/<repo>/pull/<number>/files#r<commentId>",
  "thread_id": "GraphQL-node-ID-for-thread-resolution",
  "verdict": "RESOLVED or UNRESOLVED"
}
```

#### `title` — rules

≤ 80 characters, no truncation markers; no `<username>:` prefix (the renderer shows the reviewer); no verbatim copy of the comment's first line — strip Markdown markers, emoji, and severity labels (`Suggestion:`, `Nit:`, …); an imperative or noun phrase describing the requested change. Good: `Add fee-headroom guard to transfer_with_change_address`. Bad: `thepastaclaw: **🟡 Suggestion: \`transfer_with_change_address\` skips the \`Re...`.

#### `location_permalink` — rules

**Emit `location_permalink` whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all present** — standalone reports never see the coordinator's derive pass. Template: `https://github.com/{owner}/{repo}/blob/{commit}/{path}{anchor}` — `{owner}/{repo}` from `metadata.project`; `{commit}` the full 40-char SHA; `{path}` = `location` minus the trailing `:line`/`:start-end` suffix (split at the LAST `:` — paths may contain `:`), URL-encoding spaces, `#`, `?`, non-ASCII; `{anchor}` = `#L{line}` or `#L{start}-L{end}`. Example: `src/auth.rs:42-56` in `octo/widgets` → `https://github.com/octo/widgets/blob/<sha>/src/auth.rs#L42-L56`.

**Omit** (never an empty string) when project or commit is missing, `location` has no `:line`/`:start-end` suffix, or the suffix isn't a valid integer/range — the coordinator's `_build_permalink` rejects those too, and emitting one breaks producer/coordinator parity.

- **Resolved** comments: `likelihood=0.0, impact=0.0, relevance=0.0` — the Informational floor (`claudius:severity` § 3), `verdict: "RESOLVED"`. `recommendation` describes what was done — for threads trusted via `isResolved: true` (step 3), state it was already resolved on GitHub rather than inventing an unverified fix description. The coordinator derives `severity = 1` (INFO) from the floats.
- **Unresolved** comments: assess `likelihood` and `impact` per `claudius:severity` (blast radius folds into `impact`, capped by the finding's backstop zone). Rate `relevance` as PR-goal fit, not blast radius: the comment addresses the PR's core change ≈ `1.0`; adjacent/tangential suggestion ≈ `0.5`; pre-existing concern unrelated to this PR's diff ≈ `0.1` — do NOT default to `1.0`. The coordinator derives the integer `severity` band; never hand-type a label. Set `verdict: "UNRESOLVED"`; `recommendation` describes what remains.
- `thread_id`: from `pull_request_read` `get_review_comments` (or `gh-list-review-threads.sh` fallback). Needed for step 8.
- **Merge class** (coordinator-inline producer exception — see `claudius:report-format`): RESOLVED comments omit `merge_class` (informational carve-out). Classify UNRESOLVED per `claudius:severity` § Merge Classification — `blocking` only when the concern trips a blocker gate (`intent_basis` names the gate ID plus the reviewer's request as evidence); otherwise `non_blocking` (in/adjacent to the change) or `out_of_scope_follow_up` — the latter is reported for the user's attention, never filed anywhere by this skill (`claudius:severity` § `out_of_scope_follow_up`).

**Do NOT emit** (coordinator/validator-owned): `overall_severity`, `metadata.repository`, `ai_assessment`, `ai_verdict`, `ai_verdict_confidence`, and the derived integer `severity` when emitting floats (the coordinator overrides). `likelihood`/`impact`/`relevance` are required on every comment — without all three the coordinator cannot derive `overall_severity` and the schema rejects the finding. The `validate-findings` skill is the only documented path to populate floats post-hoc.

**Optional**: `code_snippets` — when the comment quotes source you verified, attach as `[{language, caption, content}]`; never invent one.

### Numbering

Sequential IDs: `CMT-001`, `CMT-002`, … Order: unresolved first (severity descending), then resolved.

## 6. Validate Report

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 7. Render and Present

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py report.json --format md
```

Present the rendered markdown to the user. Optionally generate HTML (`--format html`). The user can also invoke `triage-findings report.json` for interactive browser-based triage of unresolved comments.

## CI Log Retrieval

See `git-and-github` skill § Context Management for the subagent delegation pattern. Always delegate `get_job_logs` fetches to a subagent that extracts the relevant failure information.

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
- Inline thread replies: `mcp__plugin_claudius_github__add_reply_to_pull_request_comment` (`comment_id` = thread's first comment)
- PR-level replies: `mcp__plugin_claudius_github__add_issue_comment`
- Keep replies concise: what was done, what remains, relevant commit reference

**Resolving bot threads** (fixed only) via the wrapper script (see `git-and-github` safety rule #10 for sandbox requirements):

```bash
# GraphQL node IDs (PRRT_*) — pass directly:
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <PRRT_id> [PRRT_id ...]

# REST IDs from pull_request_read (discussion_r* or numeric databaseId) — use enhanced mode:
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <owner/repo> <pr_number> --id discussion_r123 --id 456 [...]
```

Thread resolution has no MCP equivalent — the wrapper uses a GraphQL mutation directly. The `--id` form auto-converts `discussion_r*`/numeric IDs to thread node IDs; mix freely with `PRRT_*` in one invocation. Never resolve partially-addressed threads.

With a triage-role token, wrap the entire script invocation in `ghsudo` per the standing fallback convention; ambient bot auth commonly returns 403 for `ResolveReviewThread`.
