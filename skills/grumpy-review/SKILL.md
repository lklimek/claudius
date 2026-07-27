---
name: grumpy-review
description: "Parallel-agent code review for quality, security, dependencies, and docs. Use for reviews, audits, or quality assessments. Produces deduplicated severity-ranked report."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Bash(*consolidate_reports.py *), Bash(*validate_report.py *), Bash(*generate_review_report.py *), Bash(*lint_ephemeral_ids.py *), Bash(which *), Bash(rg *), Bash(ctags *), Bash(global *), Bash(gtags *), Bash(tree-sitter *), Bash(gh search code*), Bash(mkdir *), Agent, SendMessage
---

# Code Review Methodology

Systematic review using parallel specialist agents; produces a consolidated report with severity-ranked, deduplicated findings.

## Tone

Keep the Claudius/Skippy persona — sarcastic superiority, theatrical sighs, dry wit — with extra grumpiness about the code: complain, express disbelief at obvious mistakes, be opinionated. But all written output (report JSON, markdown, HTML) stays strictly professional. Grumpiness is for the human; the report is for posterity.

**Argument**: `$ARGUMENTS` — optional scope description (e.g., "feat/zk branch", "packages/auth/", "last 5 commits"). If empty, review all changes on the current branch vs the main branch.

## 1. Scope the Review

```bash
# If reviewing a branch
BASE_BRANCH=<main-branch>
git log $BASE_BRANCH..HEAD --oneline
git diff $BASE_BRANCH...HEAD --stat

# If reviewing specific paths
git diff $BASE_BRANCH...HEAD -- <paths>
```

Assess scale:
- **Trivial** (< 200 lines, < 5 files, single language): 1 agent — the opposite-tier fallback reviewer (see §2 Trivial reviews), prompted with `security-best-practices` and `coding-best-practices` skills. Skip the consolidation pipeline; the agent writes the report directly.
- **Small** (< 500 lines, < 10 files) through **Medium** (500-5000 lines, 10-50 files): the fixed 3-agent core trio (§2 Core agents) regardless of size. Add `technical-writer-trillian` for doc-heavy changes.
- **Large** (5000+ lines, 50+ files): same 3 core roles, scaled via multiple parallel copies per file group — see §2 Scaling.

## 2. Select Agent Mix

### Trivial reviews (single agent)

Skip the multi-agent pipeline and the fixed trio; spawn exactly ONE fallback reviewer, chosen for maximum independence from how the code was authored:

- **Authored on Opus** (e.g. `developer-bilby` at its `opus` default, or an opus-pinned workflow Implementation phase) → **`claudius:qa-engineer-marvin` on `sonnet`** — opposite-tier independent check.
- **Authored on Sonnet** → **`claudius:project-reviewer-adams` on `opus`** — opposite-tier independent check.
- **Tier unknown/unclear** (human-authored, ambiguous/absent git history, mixed authorship) → default to **`claudius:qa-engineer-marvin` on `sonnet`**.

Determine the authoring tier from `git log` (commit author/trailer, PR metadata, or the invoking workflow's recorded model selection) before spawning; if genuinely indeterminate, use the default above.

The single agent stands in for the entire trio — its prompt must cover security, structural, and adversarial-correctness concerns in one pass; instruct it to also apply the `security-best-practices` and `coding-best-practices` checklists. It writes the report JSON directly — no consolidation. Since §5b never runs on this path, the coordinator assigns `merge_class`/`intent_basis` inline after the producer returns (per `severity` skill § Merge Classification), before rendering.

### Core agents (always include — fixed trio, every non-trivial review)

| Agent (`subagent_type`) | Model | Focus |
|---|---|---|
| `claudius:security-engineer-smythe` | opus | OWASP Top 10, injection, concurrency, panics, DoS, known vulns |
| `claudius:project-reviewer-adams` | opus | Cross-artifact consistency, convention adherence, doc accuracy, structural/idiom code quality (readability, naming, DRY, cross-file duplication, maintainability), specialist orchestration |
| `claudius:qa-engineer-marvin` | sonnet | Adversarial/correctness code quality — actually running tests and lints, edge cases, ownership/panic/error-handling bugs, independent verification against ground truth |

All three are ALWAYS included for any non-trivial review — no separate per-language conditional agent. Adams and Marvin jointly cover the code-quality slice `developer-bilby` used to own alone (see Focus column for the split); `developer-bilby` no longer participates in code review in any capacity — implementation-only.

### Language best-practices preload

`project-reviewer-adams` and `qa-engineer-marvin` preload the matching `*-best-practices` skill(s) — `rust-best-practices`, `python-best-practices`, `go-best-practices`, `frontend-best-practices` — for whichever language(s) the diff touches. Name the specific skill(s) explicitly in each spawn prompt.

### Other conditional agents

| Condition | Agent (`subagent_type`) | Focus |
|---|---|---|
| Documentation changes | `claudius:technical-writer-trillian` | Accuracy, completeness, API docs, changelog |

For crypto-heavy code or significant dependency changes, expand the single security-engineer's prompt to include crypto soundness and dependency audit — do NOT spawn a second instance.

### Scaling for large codebases

For 50+ files / 5000+ lines, spawn multiple agents of the same type with different file scopes.

## 3. Craft Agent Prompts

Beyond the general agent prompt requirements, every review agent prompt MUST include:

1. **Comparison base**: how to see what changed (`git show <base>:<file>` or `git diff`)
2. **Finding format**: the severity levels and structure below
3. **Review checklists**: embed relevant checklist content or rely on preloaded skills
4. **BP preload**: every spawned reviewer (`security-engineer-smythe`, `project-reviewer-adams`, `qa-engineer-marvin`, `technical-writer-trillian`, etc.) MUST preload `coding-best-practices` so its Cross-Cutting Rules govern every finding — state this explicitly in each spawn prompt
5. **UX/DX lens**: assess how findings affect end-user workflows and developer experience, not just code correctness
6. **CI context**: when MemCan/WebSearch are unavailable (e.g., CI), instruct: "Do not use memcan tools or WebSearch/WebFetch."
7. **File output**: use the Write tool for creating files — never `cat > file` or heredoc redirections

### Finding format (JSON)

Agents MUST write findings to the specified file path as a JSON array of `finding_section` objects:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|dependencies|documentation|call_tree",
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

**Required finding fields**: `id`, `risk`/`impact`/`scope` (floats 0.0–1.0), `title`, `location`, `description`, `recommendation`. See `claudius:severity` for the OWASP-normalized recipes producing the float trio and the band table the coordinator uses to derive integer `severity`. Rate `scope` as real blast radius per `claudius:severity` — never default it to `1.0`. The float trio is the single source of truth; never hand-type a severity label.

**Optional**: `tags`, `impact_description` (Markdown impact narrative; the numeric `impact` float is separate), `code_snippets` (only when you captured the exact source during analysis — never invent one).

**Producers must NOT emit** (downstream-owned): `overall_severity`, `location_permalink`, `metadata.repository`, `ai_assessment`, `ai_verdict`, `ai_verdict_confidence`, `merge_class`, `intent_basis`, and the derived integer `severity` when emitting floats. `risk`/`impact`/`scope` are required — without all three the coordinator cannot derive `overall_severity` and the schema rejects the finding. The `validate-findings` skill is the only documented path to populate floats post-hoc.

**Metadata**: emit `metadata.commit` as the full 40-character SHA (`git rev-parse @{u}`, falling back to `git rev-parse HEAD` when the branch has no upstream — use the pushed commit so permalinks resolve on GitHub; not `--short`); omit when not in a git repo. The coordinator derives `metadata.repository` from `git remote get-url origin` — producers do not emit it.

**ID prefixes**: `SEC-` security, `PROJ-` project, `QA-`/`CODE-`/`RUST-`/`PY-`/`GO-`/`FE-` code quality (jointly owned by `project-reviewer-adams` and `qa-engineer-marvin` — see `report-format`'s ID-prefix table; prefix reflects finding category/language, not agent identity), `DOC-` docs, `CALL-` call-tree. Agents assign provisional sequential IDs within their prefix (e.g., `SEC-001`, `SEC-002`); collisions across parallel agents are fine — consolidation (5c) deduplicates and reassigns final IDs.

**Location** MUST include the full file path (e.g., `src/auth.rs:42-56`), never bare line numbers.

**Severity levels**: CRITICAL > HIGH > MEDIUM > LOW > INFO (see `severity` skill).

**Tags**: classification references — OWASP (`A01`–`A10`), CWE, language best-practice IDs, etc. Tag ALL security findings with OWASP categories; non-security findings may omit tags.

### Call-tree inspection

When the diff modifies or removes any function/method declaration, every code-quality reviewer agent MUST run a deep transitive in-repo caller walk before emitting findings. Methodology: [references/call-tree-walk.md](references/call-tree-walk.md) — read it once per review and follow the steps.

Finding shape: `category: "call_tree"`, ID prefix `CALL-` (provisional from producer, coordinator reassigns). Every `call_tree` finding's `description` MUST start with a `Walked via: <tool>` line so the reader can judge walk depth and tool quality.

Skip the walk for pure additions, doc-only PRs, and changes confined to test files.

### Ephemeral-ID lint

After each agent emits findings, run the dumb ephemeral-ID lint against the diff:

```bash
git diff $BASE_BRANCH...HEAD | python3 ${CLAUDE_SKILL_DIR}/../../scripts/lint_ephemeral_ids.py --diff
```

For each hit, judge genuine violation vs quoted/escaped example (a code fence demonstrating the rule, a test fixture asserting it, this lint's own docstring). Dismiss in-skill examples; promote genuine violations to `code_quality` findings with `tags: ["ephemeral-id-reference"]` and ID prefix `CODE-` (coordinator-assigned). The lint always exits 0 — judgement is yours.

## 4. Spawn Agents

This skill runs inline (not forked) specifically so it can spawn reviewer agents. For any non-trivial review, confirm the `Agent` tool is available before fanning out. If not (e.g. executing inside a subagent, which cannot spawn nested agents), STOP and report that the review cannot fan out — do NOT silently fall back to a single self-run review. The single-agent TRIVIAL path in §1/§2 is the only legitimate one-agent review; every non-trivial review REQUIRES fan-out.

Spawn all agents in parallel per the general spawning guidelines, with fixed per-role model tiering: `claudius:security-engineer-smythe` on `opus`, `claudius:project-reviewer-adams` on `opus`, `claudius:qa-engineer-marvin` on `sonnet` (matches `claudius:delegate` § Token Economy). This replaces the old "opus for all by default" rule.

**Model override (user-requested; confirm before downgrading Smythe)**: on explicit request (e.g. "review with Sonnet") the user may force a uniform model override across all 3 agents. Apply it to Adams and Marvin freely. Before applying an override that would downgrade `security-engineer-smythe` below `opus`, STOP and confirm the user really means it — security depth is not silently traded away by a blanket model request. Once confirmed, apply to all three including Smythe.

Example spawn pattern:

```
Agent(subagent_type="claudius:security-engineer-smythe", model="opus", prompt="...", name="security-auditor")
Agent(subagent_type="claudius:project-reviewer-adams", model="opus", prompt="...", name="project-reviewer")
Agent(subagent_type="claudius:qa-engineer-marvin", model="sonnet", prompt="...", name="qa-reviewer")
```

## 5. Consolidate Findings

After all agents complete, use the two-phase consolidation script. It automates the mechanical work (flattening, duplicate detection, ID assignment, statistics), leaving judgment calls (dedup merging, severity re-assessment, executive summary) to you.

### 5a. Phase 1 — Prepare

Flatten all agent reports, detect duplicate candidates, scan for INTENTIONAL comments:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/consolidate_reports.py prepare \
    security-engineer:${TMPDIR:-/tmp}/security-findings.json \
    project-reviewer:${TMPDIR:-/tmp}/project-findings.json \
    qa-engineer:${TMPDIR:-/tmp}/qa-findings.json \
    --repo-root $(git rev-parse --show-toplevel) \
    --output ${TMPDIR:-/tmp}/intermediate.json \
    --metadata '{"project":"...","date":"...","branch":"...","commit":"..."}'
```

Produces `intermediate.json`: flattened `raw_findings` (with agent attribution), `duplicate_groups` (candidate clusters with overlap reasons), `intentional_downgrades` (findings near INTENTIONAL comments), and `section_positives`.

### 5b. Review and merge (LLM judgment)

Read `intermediate.json` and decide:

1. **Duplicate resolution**: per `duplicate_groups` entry, merge (keep the most detailed description, union tags) or keep separate. Remove redundant findings.
2. **INTENTIONAL downgrade**: downgrade each `intentional_downgrades` finding to `INFO` — deliberate engineering decisions from previous triage.
3. **Severity re-evaluation**: load the `severity` skill (`/severity`), then re-assess every finding strictly against its criteria — agents often over-inflate.
4. **Merge classification**: assign `merge_class` (+ `intent_basis` for `blocking`) to every non-informational finding per `severity` skill § Merge Classification. Use the intent digest when the invoker supplied one (review-pr); with no PR context, derive intent from your own knowledge of the work's goal — the coordinator often knows the bigger picture the producers don't. Severity never determines `merge_class`.
5. **Merge sections**: combine same-category agent sections into unified sections.
6. **Executive summary**: write `overall_assessment`, `summary_text`, `verdict_text`, `verdict_action` — LLM-authored, but it must not contradict the merge classification; reflect every valid `blocking` finding.
7. **Agent stats**: record per-agent unique vs redundant counts.

Write the result as `merged-findings.json`:

```json
{
  "metadata": { "project": "...", "date": "...", ... },
  "executive_summary": { "overall_assessment": "...", ... },
  "findings": [ { "title": "...", "category": "...", "findings": [...], "positives": "..." } ],
  "agent_stats": [ { "agent": "...", "unique": N, "redundant": N } ],
  "top_findings_override": null,
  "remediation_override": null
}
```

Findings do NOT need `id` fields — phase 2 assigns them. Set `top_findings_override`/`remediation_override` to a JSON array to override auto-generation, or `null` to auto-generate.

### 5c. Phase 2 — Assemble

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/consolidate_reports.py assemble \
    --input ${TMPDIR:-/tmp}/merged-findings.json \
    --output ${REPORT_DIR:-.}/report.json
```

Assigns sequential IDs by category (SEC-001, PROJ-001, RUST-001, etc.), computes `summary_statistics` (severity counts, category matrix, redundancy ratio), generates `top_findings` from CRITICAL/HIGH items, and creates `remediation` priority buckets. Validates against the schema and REFUSES to write output on failure (exit 1) — validation is mandatory; jsonschema is a hard requirement.

### 5d. Validate report against schema

Assemble already validates and blocks output, but re-validate manually after hand-editing the report:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json
```

If validation fails, fix `merged-findings.json` and re-run assemble. Do NOT skip validation.

### 5e. Render markdown report

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format md
```

Produces `report.md` next to the JSON file.

## 6. Iterate if Needed

If the initial review reveals areas needing deeper investigation: spawn additional agents with narrower scope, re-review specific files with different checklists, audit forked dependencies against upstream.

## 7. Additional Report Formats (Optional)

If the user requests HTML or PDF:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format html
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format pdf
```

For interactive triage, use the `claudius:triage-findings` skill with the `${REPORT_DIR:-.}/report.json` path.

## CI Log Retrieval

See `git-and-github` skill § Context Management for the subagent delegation pattern. Always delegate `get_job_logs` fetches to a subagent that extracts the relevant failure information.

## Anti-Patterns (Review-Specific)

Beyond the general anti-patterns in the Claudius agent prompt:

1. **Skipping scope assessment** — agent mix and split strategy depend on whether the review is small, medium, or large.
2. **Missing comparison base** — review agents need to know what changed; always include the git diff/show commands in the prompt.
3. **No deduplication** — multiple agents will flag the same issue (e.g., `.unwrap()` panics); always consolidate and deduplicate before presenting findings.
