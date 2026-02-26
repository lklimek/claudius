---
name: report-pdf
description: >
  Generate a professional PDF report from code review findings. Use after
  review-all completes to produce a polished, accessible PDF with charts and
  detailed findings. Leverages the document-skills:pdf skill for PDF generation.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash(python3 *), Bash(pip install *), Bash(pip3 install *), Glob, Grep
---

# PDF Report Generation

Generate a professional, accessible PDF from code review findings produced by
`review-all` or similar review workflows. Uses `document-skills:pdf` skill
(reportlab + matplotlib).

**Argument**: `$ARGUMENTS` — path to the markdown review report. If empty, use
last generated report.

## Prerequisites

Use `document-skills:pdf` skill for reportlab/matplotlib knowledge.

Install dependencies if missing (reportlab, matplotlib, numpy).

## Baseline Script

A working template is bundled at `skills/report-pdf/generate_report_pdf.py`.
Copy it to the project directory and populate only the data sections — the
template handles all styling, layout, chart generation, and page headers/footers.

Data sections to populate in the copy:
- `CONFIG` — project name, date, agent count, totals, assessment/verdict text
- `SUMMARY_TABLE` — severity × category matrix
- `TOP_FINDINGS` — top findings requiring immediate action
- `DEPENDENCY_TABLE` — CVE scan results (if applicable)
- `AGENT_STATS` — unique/redundant counts per agent
- `REMEDIATION` — priority buckets with color keys
- `FINDING_SECTIONS` — list of section dicts containing findings tuples

Security findings use 8-tuples (with OWASP tag):
(id, severity, title, owasp_tag, location, description, impact, recommendation)

Other findings use 7-tuples:
(id, severity, title, location, description, impact, recommendation)

If the template needs adjustments for a specific report (e.g., extra chart types,
different page size), make targeted edits to the copy, not the template.

## Design Requirements

### Accessibility (WCAG AA)

- Follow well-known accessibility rules
- **White background** (`#FFFFFF`), **near-black text** (`#1A1A1A`)
- Minimum 4.5:1 contrast ratio for all body text
- No light gray text on white — use `#333333` minimum for secondary text
- Ensure images and charts dimensions match free space in the document

### Color Palette

| Element | Color |
|---|---|
| Background | `#FFFFFF` |
| Body text | `#1A1A1A` |
| Secondary text | `#333333` |
| Muted text | `#666666` |
| Light background | `#F5F5F5` |
| Borders | `#DDDDDD` |
| Brand/headers | `#1B4F72` |
| Accent links | `#2471A3` |

### Severity Colors

| Severity | Color |
|---|---|
| CRITICAL | `#C0392B` |
| HIGH | `#E67E22` |
| MEDIUM | `#D4AC0D` |
| LOW | `#2E86C1` |
| INFO | `#7F8C8D` |

### Priority Colors

- Before Merge: `#C0392B` (red)
- Before Production: `#E67E22` (amber)
- Post-Deployment: `#27AE60` (green)

## Report Structure

### Part A: Executive Summary (first pages)

1. **Title block** — project name, date, reviewer count
2. **KPI boxes** — total findings, redundancy ratio, critical count
3. **Summary table** — severity × category matrix
4. **Severity pie chart** — donut style, `set_aspect("equal")`
5. **Category bar chart** — horizontal stacked bars by severity
6. **Top 5 table** — highest-priority findings requiring immediate action
7. **Dependency table** — CVE scan results (if applicable)
8. **Agent performance chart** — unique vs redundant findings per agent
9. **Remediation priority chart** — horizontal bars: Before Merge / Before Production / Post-Deployment

### Part B: Detailed Findings (remaining pages)

For each review category (Security, Project, Code Quality, etc.):

- Section header with finding count
- Each finding rendered with:
  - **ID + Severity badge** + title (+ OWASP tag for security findings)
  - **Location**: file path in accent blue
  - **Description**: what the issue is
  - **Impact**: what could go wrong
  - **Recommendation**: how to fix
- Use `KeepTogether` to prevent findings from splitting across pages
- End each section with positive observations if any

### Footer

Every page: branded header bar + footer with attribution line:
`Co-authored by Claudius the Magnificent AI Agent | <date>`

## Data Extraction

Parse the markdown report to extract:

1. **Findings**: ID, severity, title, location, description, impact, recommendation
2. **OWASP tags**: from security finding titles (e.g., `— A01 Broken Access Control`)
3. **Severity counts**: by category for summary table and charts
4. **Agent stats**: unique/redundant counts from the Agent Summary section
5. **Dependency table**: from the Dependencies section if present

## Output

Write PDF to the same directory as the input markdown, with `.pdf` extension.
Print the output path and file size when done.
