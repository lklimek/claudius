---
name: report-format
description: "This skill should be used when emitting or consuming review findings, generating comment-assessment reports, or saving a requested table as a file. It defines the shared review schema and file-output defaults."
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *)
---

# Review Report Format

Unified format for all review findings. Schema: `schemas/review-report.schema.json`; ordinary reports declare `4.0.0`; comment-assessment reports declare `4.1.0`.

Resolve script paths from the loaded skill: Claude substitutes `${CLAUDE_PLUGIN_ROOT}`; Codex uses the installed absolute script paths in `allowed-tools`. Otherwise locate the plugin tree containing `scripts/` and `schemas/` (Codex commonly `~/.codex/claudius`); the installed skills directory and project checkout need not be that tree. Never pass unresolved placeholders to the shell.

## Table files and comment assessments

Keep ordinary table requests in chat. When asked for a table **as a file**, default to one self-contained HTML file with sticky headers, search and applicable filters; explicit format/layout requests win. Do not additionally export Markdown/CSV. Generic tables need no review JSON; reuse presentation where useful without forcing them into the finding model.

For `check-pr-comments` reports and comment tables, read [references/comment-assessments.md](references/comment-assessments.md). It extends this envelope without changing scored findings or validation-owned `ai_verdict`.

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

**Required per finding**: `id`, `likelihood`, `impact`, `relevance`, `title`, `location`, `description`, `recommendation`. The three floats (0.0–1.0, rated per the `severity` skill) are the single source of truth for severity — the schema rejects a finding missing any, and the validation pass (`review-changes` § Reports and Validation) is the only path to re-estimate them post-hoc.

- `location` — full file path with lines (`src/auth.rs:42-56`), never a bare line number.
- `tags` (optional) — OWASP category, CWE, guideline IDs. `impact_description` (optional) — Markdown narrative paired with the `impact` float.
- `description`, `impact_description`, `recommendation` are **Markdown** (CommonMark — blank line before lists, code blocks, headings); `title`, `category`, `location` are plain text.
- Check your own output: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py <file>` — the producer shape above validates as-is. Producers without Bash (e.g. Diziet) report the file path instead; their coordinator validates it.

### code_snippets

Array of `{"language", "caption", "content"}`, only when the producer captured exact source during analysis — never invent one. `language` is a free-form syntax tag (e.g. `rust`, `python`, `diff` for a raw diff hunk); `caption` is a short `path:location` label; `content` is the literal snippet text.

## Coordinator-derived / validator-owned fields — DO NOT emit

Populated downstream; producers must NOT set:

- integer `severity` and `overall_severity` — Python-computed from `likelihood`/`impact` (`severity` skill § Derivation)
- `location_permalink` — coordinator-derived. Exception for a standalone producer rendering its own final report: `check-pr-comments` § `location_permalink`
- any `metadata` field (`repository`, `commit`, `date`, `branch`)
- `ai_assessment`, `ai_verdict`, `ai_verdict_confidence` — owned by the validation pass (`review-changes` § Reports and Validation)
- `merge_class` (`blocking|non_blocking|out_of_scope_follow_up|disputed`) and `intent_basis` (string|null — for `blocking`, the gate ID plus one line of evidence, e.g. `"G-SECRET: seed phrase written to debug log at wallet/import.rs:88"`) — coordinator-assigned per `severity` skill § Merge Classification. **Exception**: coordinator-inline producers (review-pr Pass C `pr_promises`, check-pr-comments, review-dependency) emit them directly.

## File Output

Write findings files with the Write tool — never `cat > file`, `tee`, heredocs, or inline `python3`; Bash file writes are typically blocked by tool allowlists.

## ID Prefixes

| Prefix | Category | Used by |
|--------|----------|---------|
| `SEC-` | security | Smythe / security-best-practices |
| `QA-` | code_quality | Marvin / review-changes |
| `PROJ-` | project | Adams (global optimum) or Marvin (cross-artifact consistency) / review-changes |
| `CODE-`, `RUST-`, `PY-`, `GO-`, `FE-` | code_quality | generic / Rust / Python / Go / frontend — whichever of Adams or Marvin surfaced the finding |
| `CALL-` | call_tree | execution-path coverage (any reviewer) |
| `DOC-` | documentation | Trillian / technical-writing |
| `ARCH-` | architecture | Nagatha / architecture |
| `UX-` | ux | Diziet / product-design |
| `DEP-` | dependencies | review-dependency |
| `CMT-` | pr_comments | check-pr-comments — plus `reviewer`, `comment_id`, `comment_url`, `thread_id`, `verdict` fields (schema-defined) |
| `PPM-` | pr_promises | review-pr Pass C — `location` is a synthetic string (`PR-title`, `PR-body:summary-bullet-N`, `PR-body:out-of-scope-item-N`), rendered as plain text; `relevance: 1.0`. Worked example: `review-pr` § Finding emit template |

IDs are provisional — consolidation deduplicates and reassigns final IDs.

## Full reports

Wrapping sections into a complete report (envelope, metadata, `summary_statistics.merge_class_counts`), the pipeline scripts, and accepted legacy schema versions are coordinator/standalone-producer concerns — a fan-out producer never needs them: [references/coordinator-envelope.md](references/coordinator-envelope.md).
