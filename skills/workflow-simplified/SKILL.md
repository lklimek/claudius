---
name: workflow-simplified
description: "Use for bug fixes or small changes (≤200 lines). Same phase order as workflow-feature (Planning→Impl→QA→LL) with lighter ceremony. Auto-retry on failure, unattended."
---

# Simplified Workflow

Use for bug fixes, small changes (≤200 lines), small local refactorings.

Same mandatory phase order as workflow-feature, lighter ceremony. Phases are SEQUENTIAL — never skip, merge, reorder, or run phases in parallel. Within a phase, tasks and sub-phases may be combined or parallelized.

## Before You Start

Search project and global memories for relevant context before planning or dispatching agents:
1. `search_memories(query="<topic>", project="<repo>")` — discover what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — read full details of relevant memories found in step 1

These are MCP tools on the MemCan server. Use them if available. Skip silently if not.

## Unattended Operation

Runs without user interaction unless a decision is required. Accumulate reports and present a single **Final Report** when all phases complete.

## Phase 1: Planning

Lighter than workflow-feature — sub-phases may be combined into fewer agent invocations for small scope, but the concerns must still be addressed in order.

### 1a. Requirements + UX Design → `ux-designer-diziet`

Understand the problem, gather domain knowledge. For bug fixes: reproduce, identify root cause. For small features: requirements, user journey, DX impact.

**Artifact**: Brief requirements + UX notes.

### 1b. Test Case Specification → `qa-engineer-marvin`

Write test case SPECIFICATIONS (not code) covering the change. Each test case: description, expected outcome, requirement traceability.

**Artifact**: Test case specification (brief).

### 1c. Development Plan → `architect-nagatha`

Select approach, guide code placement, ensure maintainability. Task breakdown referencing test cases.

Batch small tasks so each agent gets ≥100 lines of work within same specialization.

**Artifact**: Development plan with tasks.

## Phase 2: Implementation → `developer-bilby`

For each task:
1. Write tests from Test Case Specification — must fail initially
2. Implement until tests pass
3. Self-review: deduplication, code quality, formatting, linting
4. Commit

**Pre-empt the QA audits before declaring impl done:**
1. **Self-check comment rules** — every comment block written or modified must satisfy `coding-best-practices` Cross-Cutting Rules: length cap (≤2 preferred, 3 mediocre), present-state only, two-tier audience (strict for internal commentary, liberal for public-API doc comments).
2. **Self-check duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, briefly grep the workspace, direct dependencies (per the project's manifest — `Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, etc.), and any project-defined reference repos for an existing equivalent before rolling a new one. If found and publicly exported, use it. If crate-private (or language equivalent), propose promoting it. If only partially overlaps, document the rationale for the new copy.
3. **Report rejected equivalents** — list any candidate equivalent considered and rejected, with one-line rationale, in the implementation summary so QA has context.

### TDD Discipline

1. Tests derive from the Test Case Specification, not from implementation.
2. Tests must fail before implementation begins.
3. If a test matches the spec, the *code* is wrong — fix the code, not the test.

## Phase 3: QA

Run in parallel where possible:

| Agent | Focus |
|-------|-------|
| `qa-engineer-marvin` | Three parallel passes:<br>• **Tests** — execute test cases from spec, verify all pass<br>• **Docs review (read-only)** — apply `coding-best-practices` Cross-Cutting Rules (length cap + present-state + two-tier audience) to comments and API doc comments (rustdoc, JSDoc, docstrings, godoc, etc.) introduced by the PR diff. Findings with file:line citations and proposed rewrites at `/tmp/claudius-<scope>-docs-report.md`.<br>• **Dedup audit (read-only)** — for every new publicly exported function, type, trait/interface, and module introduced by the PR, search the workspace, direct dependencies (per the project's manifest — `Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, etc.), and project-defined reference repos for equivalent functionality. Findings (high-confidence duplicates, partial overlaps, reviewed-and-rejected) with file:line citations both sides at `/tmp/claudius-<scope>-dedup-report.md`. |
| `security-engineer-smythe` | Security audit (if security-relevant change) |
| `project-reviewer-adams` | Validate Development Plan fully executed, code quality |

Scale down agent set for truly small changes — but Marvin and Adams are always required.

**Both audits are READ-ONLY by mandate** — emphasize this in the agent prompt template. Findings go to the lead, who decides follow-up:
- Trivial fixes can land in the same PR via a separate commit
- Substantial refactors land as follow-up PRs
- Findings the lead judges as wrong-call go in a "rejected with rationale" section of the report

To skip any audit, the lead must document the reason in the QA report.

No task is done until QA passes. Formatting, linting, and test passing are not optional.

## Phase 4: Lessons Learned

After QA passes, use `claudius:lessons-learned` skill to save noteworthy discoveries. Default to global memories unless strictly project-specific. Skip if nothing noteworthy. Report count saved.

## Failure & Auto-Retry

Same rules as workflow-feature:

1. Prepare failure report → auto-return to previous phase → re-execute
2. Do NOT wait for user acceptance unless a decision is required
3. Max 3 retries per phase before escalating to user

| Failed Phase | Returns To |
|---|---|
| QA (Phase 3) | Implementation (Phase 2) |
| Implementation (Phase 2) | Dev Plan (Phase 1c) |
| Dev Plan (Phase 1c) | Test Case Spec (Phase 1b) |
| Test Case Spec (Phase 1b) | Requirements (Phase 1a) |

## Final Report

Presented ONLY when all phases complete (or max retries exhausted):
- Per-phase summary, findings resolved, retry log, outstanding issues, memories saved

## Model Selection

Agents default to `model: inherit`; set model per spawn (see `grand-admiral` Token Economy). Use `sonnet` for mechanical sub-tasks and `technical-writer-trillian`; escalate stuck or complex agents to `opus`.

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations, its severity must not increase.

## Code Deduplication

Include a deduplication pass during Implementation self-review and QA code quality checks.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL spawned agents MUST use `isolation: "worktree"` — no exceptions.

**Pre-flight pattern**: see `grand-admiral` skill — Worktree Isolation. Default is Option A (local-SHA injection, no push); Option B (push first) is the explicit fallback.

**Post-wave**: verify worktree commits, merge into the feature branch, run tests, then clean up worktrees. Push only when the user explicitly authorizes it (e.g., via `/push`, `/ci-dance`, or direct instruction) — never push as an automatic step.
