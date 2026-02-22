---
name: review
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
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Task, TaskCreate, TaskUpdate, TaskList, TaskGet, SendMessage
---

# Code Review Methodology

Systematic code review using parallel specialist agents. Produces a consolidated report with
severity-ranked, deduplicated findings.

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
| `claudius:code-reviewer` | Correctness, duplication, edge cases, behavioral changes |
| `claudius:security-engineer` | OWASP Top 10, injection, concurrency, panics, DoS, known vulns |

### Conditional agents (add when relevant)

| Condition | Agent (`subagent_type`) | Focus |
|---|---|---|
| Rust code | `claudius:rust-developer` | Idioms, ownership, error handling, clippy compliance |
| Go code | `claudius:go-developer` | Idioms, error wrapping, concurrency, table-driven tests |
| Python code | `claudius:python-developer` | PEP 8, type hints, async patterns, pytest |
| Frontend code | `claudius:frontend-developer` | TS/JS patterns, React/Vue, CSS, accessibility |
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

### Finding format

All agents must use this format:

```markdown
### <ID> (<Severity>): <Title> — <OWASP Category>
- **Location**: `<file>:<line>`
- **Description**: What the issue is and why it matters
- **Impact**: What could go wrong
- **Recommendation**: How to fix it
```

Severity levels: **CRITICAL > HIGH > MEDIUM > LOW > INFO**

INFO is reserved for positive observations and praise — anything that may require action
must be LOW or higher.

OWASP categories (tag ALL security findings):
- **A01**: Broken Access Control
- **A02**: Cryptographic Failures
- **A03**: Injection / Input Validation
- **A04**: Insecure Design
- **A05**: Security Misconfiguration
- **A06**: Vulnerable and Outdated Components
- **A07**: Identification and Authentication Failures
- **A08**: Software and Data Integrity Failures
- **A09**: Security Logging and Monitoring Failures
- **A10**: Server-Side Request Forgery

Non-security findings (code quality, Rust idioms, documentation) do not need OWASP tags.

## 4. Spawn Agents

Spawn all agents in parallel following the general spawning guidelines. Use `model: "opus"`
for thorough analysis.

Example spawn pattern:

```
Task(subagent_type="claudius:security-engineer", model="opus", prompt="...", name="security-auditor")
Task(subagent_type="claudius:code-reviewer", model="opus", prompt="...", name="code-reviewer")
Task(subagent_type="claudius:rust-developer", model="opus", prompt="...", name="rust-reviewer")
```

## 5. Consolidate Findings

After all agents complete:

### 5a. Collect reports
Read all agent output files from `/tmp/claude-1000/`.

### 5b. Deduplicate
Many findings appear in multiple reports (e.g., `.unwrap()` panics found by both code-reviewer
and security-engineer). Merge duplicates, keeping the most detailed description.

### 5c. Classify and rank
- Assign unified IDs: `SEC-001`, `SEC-002`, ... for security; `CODE-001`, ... for quality;
  `RUST-001`, ... for language-specific; `DOC-001`, ... for documentation
- Ensure every security finding has an OWASP category tag
- Rank by severity, then by impact

### 5d. Build consolidated report

Structure:

```markdown
# Code Review Report: <scope>

## Executive Summary
- Overall assessment (1-2 sentences)
- Findings summary table (severity counts by category)
- Top 5 findings requiring action

## Part I: Security Findings
All security findings with OWASP tags. Merged from security-engineer + OWASP review.

## Part II: Code Quality
Correctness, duplication, edge cases, behavioral issues.

## Part III: Language Best Practices
Rust/Go/Python/TS-specific findings.

## Part IV: Dependencies (if reviewed)
CVE scan results, supply chain risks, fork audits.

## Part V: Documentation (if reviewed)
Accuracy, completeness, missing docs.

## Recommendations
Prioritized: Before Merge > Before Production > Post-Deployment
```

## 6. Iterate if Needed

If initial review reveals areas needing deeper investigation:
- Spawn additional agents with narrower scope
- Re-review specific files with different checklists
- Audit forked dependencies against upstream

## Anti-Patterns (Review-Specific)

See the general anti-patterns in the Claudius agent prompt. Additional review-specific pitfalls:

1. **Skipping scope assessment**: Always assess scale first. The agent mix and split strategy
   depend on whether the review is small, medium, or large.
2. **Missing comparison base**: Review agents need to know what changed. Always include the
   git diff or git show commands in the prompt.
3. **No deduplication**: Multiple agents will flag the same issue (e.g., `.unwrap()` panics).
   Always consolidate and deduplicate before presenting findings.
