---
name: report-format
description: "Unified review report format for all finding-producing agents. Load when emitting or consuming review findings."
allowed-tools: ["Bash(*validate_report.py *)", "Bash(*consolidate_reports.py *)", "Bash(*generate_review_report.py *)"]
---

# Review Report Format

Unified format for all review findings. Schema: `schemas/review-report.schema.json` (v2.0.0).

## Finding Structure

Agents emit a JSON array of `finding_section` objects:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|dependencies|documentation|pr_comments",
    "findings": [
      {
        "id": "PREFIX-001",
        "severity": 5,
        "title": "Short finding title",
        "tags": ["A03 Injection", "CWE-79"],
        "location": "src/auth.rs:42-56",
        "description": "What the issue is and why it matters",
        "impact": "What could go wrong",
        "recommendation": "How to fix it"
      }
    ],
    "positives": "Optional positive observations"
  }
]
```

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | `PREFIX-NNN` -- see ID Prefixes below |
| `severity` | integer | 5=CRITICAL, 4=HIGH, 3=MEDIUM, 2=LOW, 1=INFO |
| `title` | string | Short finding title |
| `location` | string | Full file path with lines: `src/auth.rs:42-56` -- never bare line numbers |
| `description` | string | What the issue is and why it matters |
| `recommendation` | string | How to fix it |

**Optional**: `tags` (OWASP, CWE, etc.), `impact` (what could go wrong).

## Long-Text Field Format

These fields are **Markdown** by default — agents emit Markdown markup, renderers parse it as CommonMark:

- `description`
- `impact`
- `recommendation`
- `executive_summary.summary_text`, `executive_summary.verdict_text`

Use `**bold**`, `## headings`, `` `code spans` ``, fenced code blocks, lists, and `[links](url)` to structure long-form content. Single-line fields (`title`, `severity`, `category`, `location`, etc.) stay plain text.

**For agents**: write descriptions as essays — `## Section headings`, `**bold callouts**`, `` `code references` ``, fenced code for snippets, lists for enumeration. Renderers handle formatting; you write content.

**For consumers**: parse long-text fields as CommonMark Markdown. Reference renderer: `scripts/generate_review_report.py` — HTML uses the `markdown` Python package, PDF walks the parsed HTML to ReportLab mini-XML. Markdown output passes through verbatim.

## File Output

When writing findings to a file, ALWAYS use the Write tool — never use Bash commands like `cat > file`, `tee`, heredoc redirects, or inline `python3` scripts for file creation. The Write tool is allowed in all CI environments; Bash file-writing commands are typically blocked by tool allowlists.

## ID Prefixes

| Prefix | Category | Used by |
|--------|----------|---------|
| `SEC-` | security | security-engineer-smythe |
| `QA-` | code_quality | qa-engineer-marvin |
| `PROJ-` | project | project-reviewer-adams |
| `CODE-` | code_quality | developer-bilby (generic) |
| `RUST-` | code_quality | developer-bilby (Rust) |
| `PY-` | code_quality | developer-bilby (Python) |
| `GO-` | code_quality | developer-bilby (Go) |
| `FE-` | code_quality | developer-bilby (frontend) |
| `DOC-` | documentation | technical-writer-trillian |
| `CMT-` | pr_comments | check-pr-comments |
| `DEP-` | dependencies | review-dependency |

IDs are provisional -- the consolidation step deduplicates and reassigns final IDs.

## Domain-Specific Fields

Agents may add context to `description` and `tags` per their domain:

- **security-engineer**: include OWASP category and CWE in `tags`, CVE references and evidence in `description`
- **qa-engineer**: include requirement reference, expected vs actual behavior in `description`
- **check-pr-comments**: include `reviewer`, `comment_id`, `comment_url`, `thread_id`, `verdict` fields (schema-defined)

## Report Pipeline Tools

| Tool | Purpose | Usage |
|------|---------|-------|
| `scripts/validate_report.py` | Validate report JSON against schema | `python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json` |
| `scripts/consolidate_reports.py` | Merge multiple agent reports, deduplicate findings | `python3 ${CLAUDE_SKILL_DIR}/../../scripts/consolidate_reports.py agent1.json agent2.json -o consolidated.json` |
| `scripts/generate_review_report.py` | Render consolidated report as Markdown/HTML | `python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py consolidated.json` |

## Full Report Envelope

For complete reports (grumpy-review, check-pr-comments), wrap finding sections in:

```json
{
  "schema_version": "2.0.0",
  "metadata": { "project": "...", "date": "YYYY-MM-DD" },
  "executive_summary": { "overall_assessment": "..." },
  "summary_statistics": { "total_findings": 0, "severity_counts": {} },
  "findings": []
}
```

See `schemas/review-report.schema.json` for complete envelope schema.
