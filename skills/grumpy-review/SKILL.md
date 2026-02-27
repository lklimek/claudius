---
name: grumpy-review
description: >
  Comprehensive code review methodology using parallel specialist agents. Use this skill whenever
  performing a code review, security audit, or quality assessment of a codebase, branch, or set of
  changes. Covers: code quality, security (with OWASP classification), cryptographic soundness,
  dependency security, language best practices, and documentation. Produces a consolidated report
  with deduplicated, severity-ranked findings. Designed for large codebases where parallel agents
  provide thorough coverage.
agent: claudius
context: fork
model: opus
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Bash(python3 *), Task, TaskCreate, TaskUpdate, TaskList, TaskGet, SendMessage
---

# Code Review Methodology

Systematic code review using parallel specialist agents. Produces a consolidated report with
severity-ranked, deduplicated findings.

## Tone

Keep the Claudius/Skippy persona — sarcastic superiority, theatrical sighs, dry wit. Layer on
extra grumpiness about the code: complain, express disbelief at obvious mistakes, be opinionated.
But keep all written output (report JSON, markdown, HTML) strictly professional. The grumpiness
is for the human; the report is for posterity.

**Argument**: `$ARGUMENTS` — optional scope description (e.g., "feat/zk branch", "packages/auth/",
"last 5 commits"). If empty, review all changes on the current branch vs the main branch.

## 1. Scope the Review

Determine what to review:

```bash
# If reviewing a branch
BASE_BRANCH=<main-branch>
git log $BASE_BRANCH..HEAD --oneline
git diff $BASE_BRANCH...HEAD --stat

# If reviewing specific paths
git diff $BASE_BRANCH...HEAD -- <paths>
```

Assess scale:
- **Small** (< 500 lines, < 10 files): 2 agents suffice
- **Medium** (500-5000 lines, 10-50 files): 3-4 agents
- **Large** (5000+ lines, 50+ files): 5+ agents, split by file groups

## 2. Select Agent Mix

Choose agents based on what the code does. Not every review needs every agent type.

### Core agents (always include)

| Agent (`subagent_type`) | Focus |
|---|---|
| `claudius:project-reviewer` | Cross-artifact consistency, convention adherence, doc accuracy, specialist orchestration |
| `claudius:security-engineer` | OWASP Top 10, injection, concurrency, panics, DoS, known vulns |

### Language specialists (add per language in scope)

These agents handle **code quality reviews** — readability, idioms, error handling, duplication, performance. Always include the relevant language specialist; the project-reviewer does NOT cover language-specific code quality.

| Condition | Agent (`subagent_type`) | Focus |
|---|---|---|
| Rust code | `claudius:rust-developer` | Code quality, idioms, ownership, error handling, clippy compliance |
| Go code | `claudius:go-developer` | Code quality, idioms, error wrapping, concurrency, table-driven tests |
| Python code | `claudius:python-developer` | Code quality, PEP 8, type hints, async patterns, pytest |
| Frontend code | `claudius:frontend-developer` | Code quality, TS/JS patterns, React/Vue, CSS, accessibility |

### Other conditional agents

| Condition | Agent (`subagent_type`) | Focus |
|---|---|---|
| Cryptographic code | `claudius:security-engineer` (second instance) | Crypto soundness, algorithm choice, key management |
| New/updated dependencies | `claudius:security-engineer` | Dependency audit, CVE scan, supply chain risk |
| Documentation changes | `claudius:technical-writer` | Accuracy, completeness, API docs, changelog |

### Scaling for large codebases

For large reviews (50+ files, 5000+ lines), spawn multiple agents of the same type with
different file scopes.

## 3. Craft Agent Prompts

Follow the general agent prompt requirements. In addition,
every review agent prompt MUST include these review-specific elements:

1. **Comparison base**: How to see what changed (`git show <base>:<file>` or `git diff`)
2. **Finding format**: Use the severity levels and structure defined below
3. **Review checklists**: Embed relevant checklist content or rely on the agent's preloaded skills

### Finding format (JSON)

Agents MUST output findings as a JSON file containing an array of `finding_section` objects.
Each agent writes its output to the specified file path as valid JSON:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|dependencies|documentation",
    "findings": [
      {
        "id": "PREFIX-001",
        "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO",
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

**Required finding fields**: `id`, `severity`, `title`, `location`, `description`, `recommendation`.
**Optional**: `tags`, `impact`.

**ID prefixes**: `SEC-` security, `PROJ-` project, `RUST-`/`PY-`/`GO-`/`FE-` language, `DOC-` docs.
Agents assign provisional sequential IDs within their prefix (e.g., `SEC-001`, `SEC-002`).
IDs may collide across parallel agents — the consolidation step (5c) deduplicates and reassigns
final IDs.

**Location** MUST include full file path (e.g., `src/auth.rs:42-56`), never bare line numbers.

**Severity levels**: CRITICAL > HIGH > MEDIUM > LOW > INFO (see `severity` skill).

**Tags**: classification references — OWASP (`A01`–`A10`), CWE, language best-practice IDs, etc.
Tag ALL security findings with OWASP categories. Non-security findings may omit tags.

## 4. Spawn Agents

Spawn all agents in parallel following the general spawning guidelines. Use `model: "opus"`
for thorough analysis.

Example spawn pattern:

```
Task(subagent_type="claudius:security-engineer", model="opus", prompt="...", name="security-auditor")
Task(subagent_type="claudius:project-reviewer", model="opus", prompt="...", name="project-reviewer")
Task(subagent_type="claudius:rust-developer", model="opus", prompt="...", name="rust-reviewer")
```

## 5. Consolidate Findings

After all agents complete:

### 5a. Collect reports
Read all agent JSON output files from the session temp directory. Each file is an array of
`finding_section` objects. Parse them with `json.load()`.

### 5b. Deduplicate
Many findings appear in multiple reports (e.g., `.unwrap()` panics found by both rust-developer
and security-engineer). Match by `location` + `title` similarity. Merge duplicates, keeping the
most detailed description and union of tags.

### 5c. Classify and rank
- Reassign unified IDs: `SEC-001`, `SEC-002`, ... for security; `PROJ-001`, ... for project;
  `RUST-001`/`PY-001`/`GO-001`/`FE-001`, ... for code quality; `DOC-001`, ... for documentation
- Merge agent sections with the same category into unified sections
- **INTENTIONAL downgrade**: For each finding, `grep -n 'INTENTIONAL'` in the source file
  at the finding's location. If an `INTENTIONAL(...)` comment exists on or near the flagged
  lines, downgrade the finding's severity to `INFO`. These comments are added by previous
  triage runs accepting the risk and represent deliberate engineering decisions.
- Rank by severity, then by impact

### 5d. Build structured report (JSON)

Emit a `report.json` file. This is the **primary output** — all renderers consume this format.

**Before writing the report**, read the schema to learn the exact structure:

```bash
cat schemas/review-report.schema.json
```

This is **mandatory** — do NOT guess field types or shapes from memory. The schema uses
`additionalProperties: false` everywhere, so any extra or mistyped key causes validation
failure. Omit optional top-level fields entirely rather than setting them to null.

### 5e. Validate report against schema

Before rendering, validate `report.json` against the schema. This catches structural
errors early — before renderers or triage tools choke on malformed data.

```bash
python3 scripts/validate_report.py report.json
```

Requires `python3-jsonschema` (`apt install python3-jsonschema`).
If validation fails, fix the JSON and re-validate before proceeding. Do NOT skip this step.

### 5f. Render markdown report

After validating `report.json`, generate a human-readable markdown version:

```bash
python3 scripts/generate_review_report.py report.json --format md
```

This produces `report.md` next to the JSON file.

## 6. Iterate if Needed

If initial review reveals areas needing deeper investigation:
- Spawn additional agents with narrower scope
- Re-review specific files with different checklists
- Audit forked dependencies against upstream

## 7. Additional Report Formats (Optional)

If the user requests HTML or PDF versions, invoke the renderer directly:

```bash
python3 scripts/generate_review_report.py report.json --format html
python3 scripts/generate_review_report.py report.json --format pdf
```

For interactive triage, use the `claudius:triage-findings` skill with the report.json path.

## Anti-Patterns (Review-Specific)

See the general anti-patterns in the Claudius agent prompt. Additional review-specific pitfalls:

1. **Skipping scope assessment**: Always assess scale first. The agent mix and split strategy
   depend on whether the review is small, medium, or large.
2. **Missing comparison base**: Review agents need to know what changed. Always include the
   git diff or git show commands in the prompt.
3. **No deduplication**: Multiple agents will flag the same issue (e.g., `.unwrap()` panics).
   Always consolidate and deduplicate before presenting findings.
