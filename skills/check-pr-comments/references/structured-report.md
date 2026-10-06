# Structured Report — check-pr-comments

Read only when the user explicitly asked for a report (e.g. "generate report", "with report"). Builds `report.json` for step 5; steps 6–7 (validate, render) are in SKILL.md.

Schema: `../../../schemas/review-report.schema.json` v4.0.0 (`3.x` accepted read-only for legacy reports, never for new output — this skill has no coordinator derive-pass to correct a stale version).

## Report structure

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
    { "title": "PR Comment Verification", "category": "pr_comments", "findings": [ ... ] }
  ]
}
```

`metadata.commit` must be the full 40-character SHA when present (omit for non-git directories). Omit `metadata.repository` — permalinks are built from `metadata.project`.

## Finding format

One finding per review comment:

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

IDs: sequential `CMT-001`, `CMT-002`, … Order: unresolved first (severity descending), then resolved.

### `title`

≤ 80 characters, no truncation markers; no `<username>:` prefix (the renderer shows the reviewer); no verbatim copy of the comment's first line — strip Markdown markers, emoji, severity labels (`Suggestion:`, `Nit:`, …); an imperative or noun phrase naming the requested change.

### `location_permalink`

**Emit whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all present** — standalone reports never see the coordinator's derive pass. Template: `https://github.com/{owner}/{repo}/blob/{commit}/{path}{anchor}` — `{owner}/{repo}` from `metadata.project`; `{commit}` the full 40-char SHA; `{path}` = `location` minus the trailing `:line`/`:start-end` suffix (split at the LAST `:` — paths may contain `:`), URL-encoding spaces, `#`, `?`, non-ASCII; `{anchor}` = `#L{line}` or `#L{start}-L{end}`.

**Omit** (never an empty string) when project or commit is missing, `location` has no `:line`/`:start-end` suffix, or the suffix isn't a valid integer/range — the coordinator's `_build_permalink` rejects those too, and emitting one breaks producer/coordinator parity.

### Scoring and classification

- **Resolved**: floats and `recommendation` rule are in SKILL.md step 5.
- **Unresolved**: assess `likelihood` and `impact` per `claudius:severity` (blast radius folds into `impact`, capped by the finding's backstop zone). Rate `relevance` as PR-goal fit, not blast radius: addresses the PR's core change ≈ `1.0`; adjacent/tangential ≈ `0.5`; pre-existing concern unrelated to the diff ≈ `0.1` — do NOT default to `1.0`. The coordinator derives the integer `severity`; never hand-type a label. `verdict: "UNRESOLVED"`; `recommendation` describes what remains.
- `thread_id`: from `gh-list-review-threads.sh`; needed for step 8.
- **Merge class** (coordinator-inline producer exception — `claudius:report-format`): RESOLVED comments omit `merge_class`. Classify UNRESOLVED per `claudius:severity` § Merge Classification — `blocking` only when the concern trips a blocker gate (`intent_basis` names the gate ID plus the reviewer's request as evidence); otherwise `non_blocking` (in/adjacent to the change) or `out_of_scope_follow_up` — reported for the user's attention, never filed anywhere by this skill (`claudius:severity` § `out_of_scope_follow_up`).

**Do NOT emit** (coordinator/validator-owned): `overall_severity`, `metadata.repository`, `ai_assessment`, `ai_verdict`, `ai_verdict_confidence`, and the derived integer `severity` when emitting floats. `likelihood`/`impact`/`relevance` are required on every comment — without all three the coordinator cannot derive `overall_severity` and the schema rejects the finding. `validate-findings` is the only documented path to populate floats post-hoc.

**Optional**: `code_snippets` — when the comment quotes source you verified, attach `[{language, caption, content}]`; never invent one.
