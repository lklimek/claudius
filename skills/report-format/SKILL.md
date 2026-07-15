---
name: report-format
description: "Unified review report format for all finding-producing agents. Load when emitting or consuming review findings."
allowed-tools: ["Bash(*validate_report.py *)", "Bash(*consolidate_reports.py *)", "Bash(*generate_review_report.py *)"]
---

# Review Report Format

Unified format for all review findings. Schema: `schemas/review-report.schema.json` (v3.2.0).

**Hard cutover**: schema versions 1.x and 2.x are no longer accepted. Producers and consumers must use v3.x (declare `3.2.0` for new reports).

## Finding Structure

Agents emit a JSON array of `finding_section` objects:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|call_tree|dependencies|documentation|pr_comments|pr_promises",
    "findings": [
      {
        "id": "PREFIX-001",
        "risk": 0.6,
        "impact": 0.7,
        "scope": 1.0,
        "title": "Short finding title",
        "tags": ["A03 Injection", "CWE-79"],
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

This is the producer-emitted shape. Integer `severity` and float `overall_severity` are not listed — the coordinator's derive pass adds them from `risk`/`impact`/`scope` (see "Coordinator-derived / validator-owned fields" below). The example validates against the v3 schema as-is because those derived fields are optional; producer skills can call `validate_report.py` on their own output before consolidation.

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | `PREFIX-NNN` -- see ID Prefixes below |
| `risk` | float | 0.0–1.0, OWASP Likelihood normalized (see `severity` skill) |
| `impact` | float | 0.0–1.0, OWASP Impact normalized (see `severity` skill) |
| `scope` | float | 0.0–1.0, blast radius — fraction of users/surface/call-sites reached, not a default-1.0 (see `severity` skill) |
| `title` | string | Short finding title |
| `location` | string | Full file path with lines: `src/auth.rs:42-56` -- never bare line numbers |
| `description` | string | What the issue is and why it matters |
| `recommendation` | string | How to fix it |

Producers MUST emit `risk`, `impact`, and `scope` — the schema rejects findings missing any of them. The coordinator computes `overall_severity` from those floats and derives integer `severity` via the band table in the `severity` skill. The `validate-findings` skill is the only documented path to re-estimate floats post-hoc when a producer's partial output reaches the coordinator without them.

**Optional**: `tags` (OWASP, CWE, etc.), `impact_description` (Markdown impact narrative; pairs with the numeric `impact` float), `code_snippets` (when the producer captured exact source during analysis — never invent one).

**Merge classification** (orthogonal to severity — see `severity` skill § Merge Classification): `merge_class` enum `blocking|non_blocking|out_of_scope_follow_up|disputed` and `intent_basis` (string|null — the exact requirement/claim justifying a `blocking` class). Coordinator-owned like `overall_severity`; the ONLY producers allowed to emit them are **coordinator-inline producers** (review-pr Pass C `pr_promises`, check-pr-comments) — same exception pattern as `location_permalink` below. `summary_statistics.merge_class_counts` (optional) carries the per-class tally.

## Coordinator-derived / validator-owned fields — DO NOT emit

Producers must NOT set these; they are populated downstream:

- `overall_severity` — Python-computed mean of `risk`/`impact`/`scope`
- `location_permalink` — Python-constructed GitHub `blob/<sha>/<path>#L<n>` URL. Coordinator-derived in the standard multi-agent pipeline; producers MUST NOT emit it there. **Exception — standalone producers** (a producer rendering its own final report with no coordinator derive-pass, canonically `check-pr-comments`): see `check-pr-comments/SKILL.md` § `location_permalink` — rules for the exact emit condition.
- `metadata.repository` — coordinator derives from `git remote get-url origin`
- `ai_assessment`, `ai_verdict`, `ai_verdict_confidence` — owned by the `validate-findings` skill
- `merge_class`, `intent_basis` — coordinator-assigned during consolidation per `severity` skill § Merge Classification. **Exception — coordinator-inline producers** (review-pr Pass C, check-pr-comments) emit them directly.
- Derived integer `severity` when emitting floats — the coordinator overrides

## Long-Text Field Format

These fields are **Markdown** by default — agents emit Markdown markup, renderers parse it as CommonMark:

- `description`
- `impact_description`
- `recommendation`
- `ai_assessment`
- `executive_summary.summary_text`, `executive_summary.verdict_text`

Single-line fields (`title`, `severity`, `category`, `location`, etc.) stay plain text.

**Markdown style for agents**: separate lists, code blocks, and headings from preceding text with a blank line (CommonMark requires this for parsing).

**For consumers**: parse long-text fields as CommonMark Markdown. Reference renderer: `scripts/generate_review_report.py` — HTML uses the `markdown` Python package sanitised through `nh3`, PDF walks the parsed HTML to ReportLab mini-XML. Markdown output passes through verbatim.

## File Output

When writing findings to a file, ALWAYS use the Write tool — never use Bash commands like `cat > file`, `tee`, heredoc redirects, or inline `python3` scripts for file creation. The Write tool is allowed in all CI environments; Bash file-writing commands are typically blocked by tool allowlists.

## ID Prefixes

| Prefix | Category | Used by |
|--------|----------|---------|
| `SEC-` | security | security-engineer-smythe |
| `QA-` | code_quality | qa-engineer-marvin |
| `PROJ-` | project | project-reviewer-adams |
| `CODE-` | code_quality | project-reviewer-adams, qa-engineer-marvin (generic) |
| `RUST-` | code_quality | project-reviewer-adams, qa-engineer-marvin (Rust) |
| `PY-` | code_quality | project-reviewer-adams, qa-engineer-marvin (Python) |
| `GO-` | code_quality | project-reviewer-adams, qa-engineer-marvin (Go) |
| `FE-` | code_quality | project-reviewer-adams, qa-engineer-marvin (frontend) |
| `DOC-` | documentation | technical-writer-trillian |
| `CMT-` | pr_comments | check-pr-comments |
| `PPM-` | pr_promises | review-pr (Pass C: promise verification) |
| `DEP-` | dependencies | review-dependency |
| `CALL-` | call_tree | reviewer call-tree inspection pass |

`CODE-`/`RUST-`/`PY-`/`GO-`/`FE-` are category prefixes, not identity-bound — either `project-reviewer-adams` or `qa-engineer-marvin` may emit them, whichever agent's pass surfaced the finding during a review (both preload the matching `*-best-practices` skill for the language(s) in scope). `developer-bilby`, which used to own these prefixes exclusively, no longer participates in code review.

IDs are provisional -- the consolidation step deduplicates and reassigns final IDs.

## Domain-Specific Fields

Agents may add context to `description` and `tags` per their domain:

- **security-engineer**: include OWASP category and CWE in `tags`, CVE references and evidence in `description`
- **qa-engineer**: include requirement reference, expected vs actual behavior in `description`
- **check-pr-comments**: include `reviewer`, `comment_id`, `comment_url`, `thread_id`, `verdict` fields (schema-defined)
- **review-pr Pass C (pr_promises)**: `location` is a synthetic string (no file:line) — use `PR-title`, `PR-body:summary-bullet-N`, or `PR-body:out-of-scope-item-N`. Renderers leave it as plain text (no permalink). Example:

```json
{
  "id": "PPM-001",
  "risk": 0.6, "impact": 0.5, "scope": 1.0,
  "title": "Title claims PDF fix, diff is gRPC tests",
  "location": "PR-title",
  "description": "Title says `fix: PDF rendering` but diff touches only `tests/grpc/`.",
  "recommendation": "Rename to `test(grpc): add coverage for retry path` or move the gRPC changes to a separate PR."
}
```

Rationale: `location` is the synthetic string `PR-title` because the finding has no commit-relative file:line target — renderers leave it as plain text and skip the permalink. `scope: 1.0` reflects that a title/body mismatch is inherently about this PR. The coordinator computes `overall_severity` and integer `severity` from the floats per `claudius:severity`.

## Report Pipeline Tools

| Tool | Purpose | Usage |
|------|---------|-------|
| `scripts/validate_report.py` | Validate report JSON against schema | `python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json` |
| `scripts/consolidate_reports.py` | Merge multiple agent reports, deduplicate findings | Two-phase `prepare`/`assemble` subcommand CLI — see `grumpy-review/SKILL.md` §5a and §5c for exact invocation |
| `scripts/generate_review_report.py` | Render consolidated report as Markdown/HTML/PDF/triage | Requires `--format {md,html,triage,pdf}` — see `grumpy-review/SKILL.md` §5e |

## Full Report Envelope

For complete reports (grumpy-review, check-pr-comments), wrap finding sections in:

```json
{
  "schema_version": "3.2.0",
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

`metadata.commit` must be a full 40-character SHA when present (the coordinator builds permalinks from it). Both `metadata.commit` and `metadata.repository` are optional — omit them for non-git directories; permalinks are silently skipped and everything else renders normally.

See `schemas/review-report.schema.json` for complete envelope schema.
