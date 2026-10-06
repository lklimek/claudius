# Structured Report — check-pr-comments additions

Read only when the user explicitly asked for a report (e.g. "generate report", "with report"). A comment-check report is an ordinary review report — the same structure `grumpy-review` produces: the finding shape, required fields and do-NOT-emit list are the `report-format` skill's, the envelope is the one its coordinator-envelope reference defines (both linked from `check-pr-comments` step 5). This file lists only what a comment check adds or does differently. Validate and render: steps 6–7 in SKILL.md.

## Envelope additions

- `metadata`: `project` = `<owner>/<repo>`, `branch`, `scope: "PR #<number> comment verification"`, `reviewers` (unique reviewer usernames), `report_type: "comment_check"`, `pr_number`. Omit `metadata.repository` — permalinks are built from `metadata.project`.
- `executive_summary`: `overall_assessment` = "X of Y review comments resolved", `verdict_action` = "N comments require attention".
- `summary_statistics`: add `verdict_counts: {"RESOLVED": <n>, "UNRESOLVED": <n>}` next to `severity_counts`.
- `findings`: one section — `title: "PR Comment Verification"`, `category: "pr_comments"`.
- `schema_version` is always `4.0.0`: this skill has no coordinator derive-pass to correct a stale version.

## Finding additions

One finding per review comment, IDs `CMT-001`, `CMT-002`, …; unresolved first (severity descending), then resolved. Beyond the standard fields:

```json
{
  "reviewer": "github-username",
  "author_type": "bot | human",
  "comment_id": 12345678,
  "comment_url": "https://github.com/<owner>/<repo>/pull/<number>/files#r<commentId>",
  "thread_id": "GraphQL-node-ID-for-thread-resolution",
  "verdict": "RESOLVED or UNRESOLVED",
  "location_permalink": "https://github.com/<owner>/<repo>/blob/<commit>/path/to/file.rs#L42-L56"
}
```

`description` = what the comment asked for; `recommendation` = what was done (RESOLVED) or what remains (UNRESOLVED). `thread_id` comes from `gh-list-review-threads.sh` and is needed for step 8.

### `title`

≤ 80 characters, no truncation markers; no `<username>:` prefix (the renderer shows the reviewer); no verbatim copy of the comment's first line — strip Markdown markers, emoji, severity labels (`Suggestion:`, `Nit:`, …); an imperative or noun phrase naming the requested change.

### `location_permalink`

This skill renders its own final report, so it emits what a coordinator would otherwise derive. **Emit whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all present.** Template: `https://github.com/{owner}/{repo}/blob/{commit}/{path}{anchor}` — `{owner}/{repo}` from `metadata.project`; `{commit}` the full 40-char SHA; `{path}` = `location` minus the trailing `:line`/`:start-end` suffix (split at the LAST `:` — paths may contain `:`), URL-encoding spaces, `#`, `?`, non-ASCII; `{anchor}` = `#L{line}` or `#L{start}-L{end}`.

**Omit** (never an empty string) when project or commit is missing, `location` has no `:line`/`:start-end` suffix, or the suffix isn't a valid integer/range — the coordinator's `_build_permalink` rejects those too, and emitting one breaks producer/coordinator parity.

### Scoring and classification

- **Resolved**: floats and `recommendation` rule are in SKILL.md step 5.
- **Unresolved**: `likelihood` and `impact` per `claudius:severity`. Rate `relevance` as PR-goal fit, not blast radius: addresses the PR's core change ≈ `1.0`; adjacent/tangential ≈ `0.5`; pre-existing concern unrelated to the diff ≈ `0.1` — do NOT default to `1.0`. `verdict: "UNRESOLVED"`.
- **Merge class** (coordinator-inline producer exception — `claudius:report-format`): RESOLVED comments omit `merge_class`. Classify UNRESOLVED per `claudius:severity` § Merge Classification — `blocking` only when the concern trips a blocker gate (`intent_basis` names the gate ID plus the reviewer's request as evidence); otherwise `non_blocking` (in/adjacent to the change) or `out_of_scope_follow_up` — reported for the user's attention, never filed anywhere by this skill (`claudius:severity` § `out_of_scope_follow_up`).
