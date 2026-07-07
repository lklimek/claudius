---
name: check-pr-comments
description: Use to verify PR review comments are addressed in code. Optionally produces triage-compatible report.
allowed-tools: Read, Write, Grep, Glob, Bash(gh pr checkout *), Bash(gh pr view *), Bash(git pull *), Bash(git fetch *), Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(*validate_report.py *), Bash(*generate_review_report.py *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-list-review-threads.sh *), Bash(*gh-resolve-review-threads.sh *), Bash(*gh-post-review-reply.sh *), Bash(which *), Bash(rg *), Bash(ctags *), Bash(global *), Bash(gtags *), Bash(tree-sitter *), Bash(gh search code*), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment, mcp__plugin_claudius_github__add_issue_comment
---

# Check PR Comments Workflow

When asked to check/triage/verify existing PR review comments, follow this workflow.

## 1. Fetch All Comments

**ALWAYS fetch fresh comments from GitHub on every invocation** -- never assume none are new; comments may have just appeared.

Use GitHub MCP tools to fetch all comment types:

- **Review threads** (inline comments with resolution status): `pull_request_read` with `method: "get_review_comments"` — returns threads with `isResolved`, `isOutdated`, `isCollapsed` metadata and grouped comments. Carry `isResolved` forward per thread — step 3 uses it to skip re-verification of already-resolved threads.
- **Review summaries**: `pull_request_read` with `method: "get_reviews"` — returns review state, body, and author.
- **PR-level comments** (non-diff): `pull_request_read` with `method: "get_comments"` — returns general PR discussion.

Paginate with `perPage` and `page` (for get_reviews/get_comments) or `perPage` and `after` cursor (for get_review_comments) to fetch all results.

If GitHub MCP is unavailable, see [gh-cli-fallback.md](references/gh-cli-fallback.md) for `gh` CLI equivalents.

## 2. Checkout and Pull the PR Branch

```bash
gh pr checkout <number>
git pull
```

## 3. Verify Each Comment Against Current Code

**Trust GitHub's resolved status — do not re-verify already-resolved threads.** For any thread where step 1's fetch returned `isResolved: true`, classify it as **Resolved** and skip the rest of this section: do not re-read the referenced code, re-run the call-tree walk, or second-guess a prior resolution. Apply the verification steps below only to threads with `isResolved: false`.

When verifying resolution, apply `coding-best-practices` Cross-Cutting Rules to the changed code. For every **unresolved** inline comment, read the file at the referenced location and **verify whether the identified issue is actually fixed** -- not just whether the code changed. Specifically:

- **Verify state before resolving — broad instructions are not authorization.** Before classifying an unresolved thread as resolved *in this session*, verify the actual code state at the referenced location matches the reviewer's request. Do NOT mark a thread resolved based on the user's blanket instruction ("just resolve everything") or on a follow-up commit message that *claims* to fix it. If a thread cannot be verified resolved against current code, classify it as `Unresolved` with an explicit "needs verification" recommendation. Surface the mismatch — never silently resolve. (Specific application of `coding-best-practices` Cross-Cutting Rules — "Verify facts before acting on broad instructions". This governs threads you are about to resolve yourself; it does not reopen threads already resolved on GitHub — see above.)
- Read the current code at the location the comment references
- Understand what the comment is asking for
- Determine if the current code satisfies the request (semantically, not just syntactically)
- For comments with multiple sub-items, verify each one independently
- A comment is only "resolved" if **all** of its sub-items are addressed
- Verify the fix achieves the intended end-user or developer experience, not just technical correctness
- **Call-tree walk on touched functions**: if the comment references a function whose body or signature was modified in the resolution commits (`git diff $RESOLUTION_BASE...HEAD -- <file>`), run the deep transitive in-repo caller walk per [../grumpy-review/references/call-tree-walk.md](../grumpy-review/references/call-tree-walk.md) on that function before declaring the thread resolved. A caller that still depends on the old contract turns a "fixed" thread into Unresolved with a CALL-tagged follow-up.

**Classify each comment's author:**
- **Bot**: username ends with `[bot]` (e.g. `dependabot[bot]`) or the GitHub API returns `type: "Bot"` for the author
- **Human**: all other authors

## 4. Present Summary

Present a concise summary directly to the user:
- Total comments checked, how many resolved vs unresolved
- For **each comment**, include Claude's assessment:
  - **Already resolved** (`isResolved: true` at fetch time): report it as resolved, citing GitHub's own status — do not restate a fix assessment you didn't perform (see step 3).
  - **Resolved by verification this session** (`isResolved: false` at fetch time, confirmed fixed against current code): confirm the fix is adequate, or flag remaining concerns if the resolution is technically present but semantically incomplete. State whether you agree the original comment was valid.
  - **Unresolved**: state your recommendation (priority and suggested approach). If you disagree with the reviewer's concern, say so with a brief reason.
- Lead with unresolved comments, then resolved
- Include the **author type** (bot/human) and the **planned action** (auto-resolve, reply, etc.) for each comment

This is the default end of the workflow. Steps 5-7 (structured report) are only produced when the user explicitly requests it (e.g. "generate report", "produce report", "with report"). Step 8 (resolve threads) applies to both flows.

---

## Optional: Structured Report (on request only)

## 5. Build Structured Report JSON

Produce a `report.json` file following the unified report schema (`../../schemas/review-report.schema.json` v3.1.0; 3.0.0 still accepted).

### Report structure

```json
{
  "schema_version": "3.1.0",
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

`metadata.commit` must be the full 40-character SHA when present (omit for non-git directories). Omit `metadata.repository` — no consumer of standalone comment-check reports needs it; permalinks (below) are built from `metadata.project` instead.

### Finding format

Each review comment becomes one finding:

```json
{
  "id": "CMT-001",
  "risk": 0.1,
  "impact": 0.1,
  "scope": 1.0,
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

The `title` is the column users see at a glance in the rendered report. The `reviewer` field is shown separately, so the title must carry only the substance.

1. **≤ 80 characters.** Hard cap. Do NOT emit a `…` / `...` truncation marker — write a title that fits.
2. **No reviewer prefix.** Never start with `<username>:` — the renderer already shows the reviewer next to the title.
3. **No verbatim copy of the comment's first line.** Strip Markdown markers (`**`, leading `>`), emoji, and severity labels (`Suggestion:`, `Issue:`, `Nit:`, `Question:`) that came from the comment body. The title summarises, not quotes.
4. **Phrase as an imperative or noun phrase describing the change requested**, not a quote of the reviewer's wording.

Good (what the comment *asks for*):
- `Add fee-headroom guard to transfer_with_change_address`
- `Rename transfer_inner to transfer`

Bad (quotes / markup / prefix / truncation):
- `thepastaclaw: **🟡 Suggestion: \`transfer_with_change_address\` skips the \`Re...`
- `> Explain when to use transfer() and when to use transfer_with...`

#### `location_permalink` — rules

**Producers MUST emit `location_permalink` whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all present.** This is the field the renderer turns into a clickable link; standalone reports never see the coordinator's derive pass, so the producer is the only place that always knows the commit. Path-only locations (no `:line`) MUST NOT carry a `location_permalink` — the coordinator's `_build_permalink` rejects them too, so emitting one would break producer/coordinator parity.

URL template:

```
https://github.com/{owner}/{repo}/blob/{commit}/{path}{anchor}
```

- `{owner}/{repo}`: split `metadata.project` on `/` (it's already in `<owner>/<repo>` form).
- `{commit}`: full 40-char SHA from `metadata.commit` (derived from `git rev-parse @{u}` with a `git rev-parse HEAD` fallback — use the pushed commit so permalinks resolve on GitHub; fall back to local HEAD only when the branch has no upstream).
- `{path}`: the file path from `location` — split off the trailing `:line` or `:start-end` suffix; the remainder is the path. (This matches the coordinator's `parse_location` regex, which anchors at end of string. Splitting at the first `:` would break paths that contain `:`.) URL-encode spaces, `#`, `?`, and any non-ASCII characters.
- `{anchor}`:
  - `#L{line}` when `location` ends in `:{line}` (single line)
  - `#L{start}-L{end}` when `location` ends in `:{start}-{end}` (range)

Examples:

- `location: "src/auth.rs:42"`, project `octo/widgets`, commit `0123…ef` →
  `https://github.com/octo/widgets/blob/0123…ef/src/auth.rs#L42`
- `location: "packages/wallet/src/transfer.rs:414-420"` →
  `…/blob/<sha>/packages/wallet/src/transfer.rs#L414-L420`

Omit `location_permalink` (do NOT emit an empty string) when commit or project is missing, when `location` lacks a `:line` or `:start-end` suffix, or when the line suffix isn't a valid integer (or a valid integer-integer range).

- **Resolved** comments: `risk = impact = 0.1`, `scope = 0.0` (the comment is satisfied — no remaining work in scope), `verdict: "RESOLVED"`. `recommendation` describes what was done — for threads trusted as already-resolved via `isResolved: true` (see step 3), state that it was already resolved on GitHub rather than inventing a fix description you didn't verify. The coordinator will derive `severity = 1` (INFO) from those floats.
- **Unresolved** comments: assess `risk`, `impact`, AND `scope` per the OWASP recipes in `claudius:severity`. Rate `scope` as the comment's real blast radius (a single call-site / narrow path ≈ `0.2`; a subsystem ≈ `0.5`; repo-wide ≈ `1.0`) — do NOT default to `1.0`. The coordinator derives the integer `severity` band; never hand-type a label. Set `verdict: "UNRESOLVED"` and let `recommendation` describe what still needs doing.
- `thread_id`: from `pull_request_read` `get_review_comments` response (or `gh-list-review-threads.sh` fallback). Needed for thread resolution in step 8.

**Do NOT emit** (coordinator/validator-owned): `overall_severity`, `metadata.repository`, `ai_assessment`, `ai_verdict`, `ai_verdict_confidence`, and the derived integer `severity` when emitting floats (the coordinator overrides). `risk`/`impact`/`scope` are required on every comment — without all three the coordinator cannot derive `overall_severity` and the schema rejects the finding. The `validate-findings` skill is the only documented path to populate floats post-hoc.

**Optional**: `code_snippets` — when the comment quotes specific source you verified, you may attach it as `[{language, caption, content}]`; never invent one.

### Numbering

Assign sequential IDs: `CMT-001`, `CMT-002`, etc. Order: unresolved first (by severity descending), then resolved.

## 6. Validate Report

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json
```

If validation fails, fix the JSON and re-validate. Do NOT proceed with invalid data.

## 7. Render and Present

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py report.json --format md
```

Present the rendered markdown report to the user. Optionally generate HTML (`--format html`) for richer display.

The user can also invoke `triage-findings report.json` for interactive browser-based triage of unresolved comments.

## CI Log Retrieval

See `git-and-github` skill § Context Management for the subagent delegation pattern. CI logs via `get_job_logs` are a prime example — always delegate to a subagent that fetches the log and extracts relevant failure information.

## 8. Resolve and Reply to Threads

Apply the following matrix **without asking for confirmation**, except where noted:

| Author | Status | Action |
|--------|--------|--------|
| Any | Already resolved (`isResolved: true`) | No action — already resolved, do not reply or attempt to resolve again |
| Bot | Fixed (verified this session) | Auto-resolve the thread (no confirmation needed) |
| Bot | Not fixed | Post a reply explaining what remains. Do NOT resolve. |
| Human | Fixed (verified this session) | Post a reply explaining what was done. Do NOT resolve. |
| Human | Not fixed | Post a reply explaining what remains. Do NOT resolve. |

**NEVER auto-resolve human-created threads** unless the user gives explicit per-invocation permission (e.g. "resolve all fixed threads" or "resolve human threads too"). Even when fully fixed, the human reviewer should resolve their own threads.

**Posting replies:**
- Inline review thread replies: `mcp__plugin_claudius_github__add_reply_to_pull_request_comment` (use `comment_id` from the thread's first comment)
- PR-level comment replies: `mcp__plugin_claudius_github__add_issue_comment`
- Keep replies concise: what was done, what remains, reference to relevant commit if applicable

**Resolving bot threads** (fixed only) using the wrapper script (see `git-and-github` safety rule #10 for sandbox requirements):

```bash
# GraphQL node IDs (PRRT_*) — pass directly:
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <PRRT_id> [PRRT_id ...]

# REST IDs from pull_request_read (discussion_r* or numeric databaseId) — use enhanced mode:
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <owner/repo> <pr_number> --id discussion_r123 --id 456 [...]
```

Thread resolution has no MCP equivalent — the wrapper script uses a GraphQL mutation directly. The `--id` form auto-converts `discussion_r*` / numeric IDs to thread node IDs; mix freely with `PRRT_*` IDs in one invocation. Never resolve threads that are only partially addressed.
