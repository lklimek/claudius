---
name: report-format
description: "This skill should be used when emitting or consuming review findings. It defines the finding JSON shape (schema v4), the fields producers must and must not emit, and the ID prefixes, for every finding-producing agent."
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *)
---

# Review Report Format

Unified format for all review findings. Schema: `schemas/review-report.schema.json`; new reports declare `schema_version` `4.0.0`.

## Finding Structure

Producers emit a JSON array of `finding_section` objects:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|call_tree|dependencies|documentation|pr_comments|pr_promises|architecture|ux",
    "findings": [
      {
        "id": "PREFIX-001",
        "likelihood": 0.6,
        "impact": 0.7,
        "relevance": 0.5,
        "title": "Short finding title",
        "tags": ["A05 Injection", "CWE-79"],
        "location": "src/auth.rs:42-56",
        "description": "What the issue is and why it matters",
        "impact_description": "What could go wrong (Markdown narrative)",
        "recommendation": "How to fix it",
        "code_snippets": [
          {"language": "rust", "caption": "auth.rs:42", "content": "let user = unwrap_token(&hdr);"}
        ]
      }
    ],
    "positives": "Optional positive observations"
  }
]
```

**Required per finding**: `id`, `likelihood`, `impact`, `relevance`, `title`, `location`, `description`, `recommendation`. The three floats (0.0–1.0, rated per the `severity` skill) are the single source of truth for severity — the schema rejects a finding missing any, and `validate-findings` is the only path to re-estimate them post-hoc.

- `location` — full file path with lines (`src/auth.rs:42-56`), never a bare line number.
- `tags` (optional) — OWASP category, CWE, guideline IDs. `impact_description` (optional) — Markdown narrative paired with the `impact` float.
- `description`, `impact_description`, `recommendation` are **Markdown** (CommonMark — blank line before lists, code blocks, headings); `title`, `category`, `location` are plain text.
- Check your own output: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py <file>` — the producer shape above validates as-is.

### code_snippets

Array of `{"language", "caption", "content"}`, only when the producer captured exact source during analysis — never invent one. `language` is a free-form syntax tag (e.g. `rust`, `python`, `diff` for a raw diff hunk); `caption` is a short `path:location` label; `content` is the literal snippet text.

## Coordinator-derived / validator-owned fields — DO NOT emit

Populated downstream; producers must NOT set:

- integer `severity` and `overall_severity` — Python-computed from `likelihood`/`impact` (`severity` skill § Derivation)
- `location_permalink` — coordinator-derived. Exception for a standalone producer rendering its own final report: `check-pr-comments` § `location_permalink`
- any `metadata` field (`repository`, `commit`, `date`, `branch`)
- `ai_assessment`, `ai_verdict`, `ai_verdict_confidence` — owned by `validate-findings`
- `merge_class` (`blocking|non_blocking|out_of_scope_follow_up|disputed`) and `intent_basis` (string|null — for `blocking`, the gate ID plus one line of evidence, e.g. `"G-SECRET: seed phrase written to debug log at wallet/import.rs:88"`) — coordinator-assigned per `severity` skill § Merge Classification. **Exception**: coordinator-inline producers (review-pr Pass C `pr_promises`, check-pr-comments, review-dependency) emit them directly.

## File Output

Write findings files with the Write tool — never `cat > file`, `tee`, heredocs, or inline `python3`; Bash file writes are typically blocked by tool allowlists.

## ID Prefixes

| Prefix | Category | Used by |
|--------|----------|---------|
| `SEC-` | security | security-engineer-smythe |
| `QA-` | code_quality | qa-engineer-marvin |
| `PROJ-` | project | project-reviewer-adams |
| `CODE-`, `RUST-`, `PY-`, `GO-`, `FE-` | code_quality | generic / Rust / Python / Go / frontend — whichever of Adams or Marvin surfaced the finding |
| `CALL-` | call_tree | reviewer call-tree inspection pass |
| `DOC-` | documentation | technical-writer-trillian |
| `ARCH-` | architecture | architect-nagatha |
| `UX-` | ux | ux-designer-diziet |
| `DEP-` | dependencies | review-dependency |
| `CMT-` | pr_comments | check-pr-comments — plus `reviewer`, `comment_id`, `comment_url`, `thread_id`, `verdict` fields (schema-defined) |
| `PPM-` | pr_promises | review-pr Pass C — `location` is a synthetic string (`PR-title`, `PR-body:summary-bullet-N`, `PR-body:out-of-scope-item-N`), rendered as plain text; `relevance: 1.0`. Worked example: `review-pr` § Finding emit template |

IDs are provisional — consolidation deduplicates and reassigns final IDs.

## Full reports

Wrapping sections into a complete report (envelope, metadata, `summary_statistics.merge_class_counts`), the pipeline scripts, and accepted legacy schema versions are coordinator/standalone-producer concerns — a fan-out producer never needs them: [references/coordinator-envelope.md](references/coordinator-envelope.md).
