# Coordinator Envelope & Pipeline Tools

Coordinator/standalone-producer concerns — a fan-out producer in a `grumpy-review` review never
touches this (`report-format` § Coordinator-derived / validator-owned fields: metadata is
coordinator-owned).

## Report Pipeline Tools

`scripts/validate_report.py report.json` (schema validation); `scripts/consolidate_reports.py
prepare`/`assemble` (merge + dedup — `grumpy-review` §5a/§5c); `scripts/generate_review_report.py
--format {md,html,triage,pdf}` (`grumpy-review` §5e). All under
`${CLAUDE_SKILL_DIR}/../../scripts/`.

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

`metadata.commit` is a full 40-character SHA when present (permalinks are built from it);
`metadata.commit` and `metadata.repository` are optional — omit for non-git directories and
permalinks are skipped. Complete envelope: `schemas/review-report.schema.json`.
