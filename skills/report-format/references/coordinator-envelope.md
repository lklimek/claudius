# Coordinator Envelope & Pipeline Tools

Coordinator/standalone-producer concerns — a fan-out producer in a `grumpy-review` review never touches this (`report-format` § Coordinator-derived / validator-owned fields: metadata is coordinator-owned).

## Report Pipeline Tools

In the plugin's `scripts/` directory; invoke by the absolute path the calling skill's `SKILL.md` provides:

- `validate_report.py report.json` — schema validation
- `consolidate_reports.py prepare` / `finalize` — dedup, merge, assemble, render (`grumpy-review` §5a/§5c)
- `generate_review_report.py --format {md,html,triage,pdf}` — re-render (HTML via `markdown` + `nh3`, PDF via ReportLab)

## Full Report Envelope

For complete reports (grumpy-review, check-pr-comments), wrap finding sections in:

```json
{
  "schema_version": "4.0.0",
  "metadata": {
    "project": "claudius",
    "date": "YYYY-MM-DD",
    "commit": "<full 40-char SHA from `git rev-parse @{u}` (fall back to `git rev-parse HEAD` when the branch has no upstream)>"
  },
  "executive_summary": { "overall_assessment": "..." },
  "summary_statistics": { "total_findings": 0, "severity_counts": {} },
  "findings": []
}
```

`metadata.commit` is a full 40-character SHA when present (permalinks are built from it); `metadata.commit` and `metadata.repository` are optional — omit for non-git directories and permalinks are skipped. `executive_summary.summary_text` / `.verdict_text` are Markdown. `summary_statistics.merge_class_counts` (optional) carries the per-class tally. Complete envelope: `schemas/review-report.schema.json`.

## Schema versions

New reports MUST declare `4.0.0`. Versions 1.x and 2.x are rejected. `3.x` is accepted read-only for in-flight reports — legacy floats migrate to the v4 field names on load, `relevance` is defaulted and must be re-rated (`severity` skill; `validate-findings`).
