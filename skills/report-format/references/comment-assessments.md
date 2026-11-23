# Comment assessments (schema 4.2)

Use the existing review envelope with `schema_version: "4.2.0"`, `metadata.report_type: "comment_check"`, and optional top-level `comment_assessments`. Existing 3.x/4.0/4.1 reports remain readable; ordinary producers still emit 4.0. Old consumers must reject an unknown version rather than drop its rows. Findings retain every existing required field and risk-scoring rule.

One row per comment/request, reply or status message; merge duplicates into one row, listing the others in `merged_thread_ids` / `merged_urls`. Reuse existing `CMT-…` IDs, author identity, metadata and permalinks. Keep IDs stable once shown. A row referring to a scored finding uses that finding's ID; other rows need their own unique IDs. Do not renumber findings independently of rows.

```json
{
  "id": "CMT-001",
  "finding_id": "CMT-001",
  "reviewer": "reviewer-login",
  "author_type": "human",
  "source_kind": "inline",
  "comment_id": 123,
  "comment_url": "https://github.com/owner/repo/pull/42#discussion_r123",
  "thread_id": "PRRT_example",
  "thread_state": "resolved",
  "location": "src/input.py:12",
  "location_permalink": "https://github.com/owner/repo/blob/COMMIT/src/input.py#L12",
  "description": "Validate input before saving.",
  "assessment": "valid",
  "reasoning": "The write still accepts invalid input.",
  "evidence": "The caller passes unchecked data.",
  "proposed_action": "Fix the validation.",
  "proposed_reply": "Validation will be added."
}
```

Required: `id`, `reviewer`, `source_kind`, `comment_url`, `description`, `reasoning`, `proposed_action`. `source_kind`: `inline`, `review_body`, `pr_comment`, `reply`, `status`. `assessment` is required for the first three: `valid`, `already_fixed`, `out_of_scope`, `wrong`. Replies/status messages may omit it. `valid` requires `finding_id` referencing a scored finding. Score actual remaining defects, including out-of-scope ones, in `findings`; acknowledgements/status messages and dismissed or already-fixed requests need no fabricated scores. `findings` may be empty; statistics count scored findings only.

`comment_id` preserves the fetched source ID: numeric database ID or GraphQL node string (PR-level `gh pr view` comments). Existing findings/wrappers retain their numeric ID contract. `thread_state` (`resolved`, `unresolved`, `unknown`) records GitHub state independently of the assessment: a resolved thread may still have a valid remaining concern. Omit thread fields for sources without threads. Omit unavailable location; never invent `n/a` code links. Source/code URLs must be absolute HTTP(S). Human-readable fields support Markdown except identity/location fields and literal `proposed_reply`.

`reasoning` explains the assessment; `evidence` records verified code/context separately. `proposed_action` and `proposed_reply` are proposals, never proof of execution. Optional `action_taken` records only completed actions. For an existing PR/issue tracking the topic, `proposed_reply` contains **only its URL**. Keep private branch/WIP information out of proposed public replies.

**4.2 row fields**, all optional; any of them, or `metadata.input_mode`, requires `4.2.0`:

- `source_quote`: verbatim span (≤ 600 chars) of the source text the row answers.
- `gates`: `[{gate, evidence}]`, each blocker gate (`severity` § 2) the concern trips; independent of `merge_class`.
- `proposed_decision`: machine form of `proposed_action`: `{kind, fixed_in?, target_pr?, target_url?, title?}`. `kind`: `resolve` (`fixed_in`: commit SHA), `fix_here`, `reject`, `handled_in_pr` (`target_pr` or `target_url`), `follow_up_pr` (existing `target_pr`, or `title` ≤ 120 for a new one), `upstream_issue` (`target_url` of the owning repository or an existing issue), `todo`.
- `recorded_decision`: a decision already on GitHub: `{kind, by: login, comment_url, quote ≤ 600}`; `kind` as above, or `deferred` / `withdrawn`.
- `merged_thread_ids`, `merged_urls`: thread node IDs and source URLs merged into the row.
- `pre_existing`: the problem exists on the base branch. `fix_size`: `XS` / `S` / `M`.
- `category`: a `check-pr-comments` step 4 slug, or `other: <2–3 words>`.

`metadata.input_mode`: `fetched` or `host_supplied`. `host_supplied` also requires `metadata.pr_number` and `metadata.commit`, `thread_id` on inline rows, `proposed_decision` on inline/review-body/PR-comment rows, and `source_quote` on review-body/PR-comment rows. 4.2 URLs are `https://`. Row IDs: `CMT-` plus three or more digits.

Render HTML with the existing generator's `--format html`: every row contains its reasoning, evidence and proposed action alongside source/code links, assessment badge and independent thread state. Markdown/PDF remain explicit opt-ins. Interactive triage controls apply to scored findings; assessment/context rows are read-only evidence, and do not authorize GitHub actions.
