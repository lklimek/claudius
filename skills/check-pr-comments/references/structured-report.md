# Structured Report — check-pr-comments additions

Read for a requested report or comment-table file. A comment-check report uses the ordinary review envelope and finding contract from `report-format`, extended by its comment-assessment contract (loaded from `check-pr-comments` step 5). This file lists only comment-check additions. Validate and render: steps 6–7 in SKILL.md.

## Envelope additions

- `metadata`: `project` = `<owner>/<repo>`, `branch`, `scope: "PR #<number> comment verification"`, `reviewers` (unique reviewer usernames), `report_type: "comment_check"`, `pr_number`. Omit `metadata.repository` — permalinks are built from `metadata.project`.
- `executive_summary`: `overall_assessment` = "X of Y review comments resolved", `verdict_action` = "N comments require attention".
- `summary_statistics`: add `verdict_counts: {"RESOLVED": <n>, "UNRESOLVED": <n>}` next to `severity_counts`.
- `findings`: one section — `title: "PR Comment Verification"`, `category: "pr_comments"`.
- Emit `schema_version: "4.2.0"` and `comment_assessments` per the `report-format` contract loaded in step 5; `metadata.input_mode`: `fetched`, or `host_supplied` in host-supplied mode. Existing 4.0/4.1 comment-check reports remain readable. Statistics count scored findings, not context rows; omit `verdict_counts` when the binary finding verdict is unused.

## Row fields (4.2)

- Step 3: an item's quote → `source_quote`; reply-chain decision → `recorded_decision`; merged duplicates → `merged_thread_ids` / `merged_urls`.
- Step 4 and the verify-only report contract: Category → `category`; Recommendation → `proposed_decision` (`proposed_action` keeps the prose); tripped gates → `gates`; pre-existing on base → `pre_existing`; fix size → `fix_size`.

## Finding additions

One scored finding per actual remaining concern; other comments live only in assessment rows. IDs `CMT-001`, `CMT-002`, … — reuse the step 4 table's IDs once shown, never re-sort; otherwise unresolved first (severity descending; out of scope after in scope), then resolved/context. A merged duplicate (step 3) is one finding: the first thread's `comment_id`/`thread_id`, the other thread links in `description`. Beyond the standard fields:

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

`tags` carries the step 4 category as `category:<slug>` (`category:other:<label>` for `other`).

Review-body and PR-comment items (SKILL.md step 3) have no thread: omit `comment_id` and `thread_id`; `comment_url` = the review's or comment's URL; `location` = the code the request concerns, else `PR #<number>` (no permalink).

`description` = what the comment asked for; `recommendation` = what was done (RESOLVED) or what remains (UNRESOLVED). `thread_id` comes from `gh-list-review-threads.sh` and is needed for step 8.

### `title`

≤ 80 characters, no truncation markers; no `<username>:` prefix (the renderer shows the reviewer); no verbatim copy of the comment's first line — strip Markdown markers, emoji, severity labels (`Suggestion:`, `Nit:`, …); an imperative or noun phrase naming the requested change.

### `location_permalink`

This skill renders its own final report, so it emits what a coordinator would otherwise derive. **Emit whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all present.** Template: `https://github.com/{owner}/{repo}/blob/{commit}/{path}{anchor}` — `{owner}/{repo}` from `metadata.project`; `{commit}` the full 40-char SHA; `{path}` = `location` minus the trailing `:line`/`:start-end` suffix (split at the LAST `:` — paths may contain `:`), URL-encoding spaces, `#`, `?`, non-ASCII; `{anchor}` = `#L{line}` or `#L{start}-L{end}`.

**Omit** (never an empty string) when project or commit is missing, `location` has no `:line`/`:start-end` suffix, or the suffix isn't a valid integer/range — the coordinator's `_build_permalink` rejects those too, and emitting one breaks producer/coordinator parity.

### Scoring and classification

- **Already fixed/dismissed/context**: assessment rows need no scored finding. Legacy RESOLVED findings remain readable with zero floats and an informational band.
- **Unresolved**: `likelihood` and `impact` per `claudius:severity`. Rate `relevance` as PR-goal fit per the `claudius:severity` § 3 scale, not blast radius — do NOT default to `1.0`. `verdict: "UNRESOLVED"`.
- **Merge class** (coordinator-inline producer exception — `claudius:report-format`): RESOLVED comments omit `merge_class`. Classify UNRESOLVED per `claudius:severity` § Merge Classification — `blocking` only when the concern trips a blocker gate in this PR's layer (`intent_basis` names the gate ID plus the reviewer's request as evidence; upstream-only → step 3 conflict, the user's call); otherwise `non_blocking` (in scope per SKILL.md step 3, necessity gate included) or `out_of_scope_follow_up` — reported for the user's decision, never filed anywhere by this skill (`claudius:severity` § 5).
