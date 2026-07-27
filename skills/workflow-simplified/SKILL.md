---
name: workflow-simplified
description: "Use for bug fixes or small changes (≤200 lines). Same phase order as workflow-feature (Planning→Impl→QA→LL) with lighter ceremony. Auto-retry on failure, unattended."
---

# Simplified Workflow

Use for bug fixes, small changes (≤200 lines), small local refactorings.

Same mandatory phase order as workflow-feature, lighter ceremony. Phases are SEQUENTIAL — never skip, merge, reorder, or run in parallel. Within a phase, tasks and sub-phases may be combined or parallelized.

## Before You Start

Search project and global memories before planning or dispatching agents (MemCan MCP tools — use if available, skip silently if not):
1. `search_memories(query="<topic>", project="<repo>")` — what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — full details of relevant hits

## Unattended Operation

Runs without user interaction unless a decision is required. Accumulate reports and present a single **Final Report** when all phases complete.

## Phase 1: Planning

Lighter than workflow-feature — sub-phases may be combined into fewer agent invocations for small scope, but the concerns must be addressed in order.

### 1a. Requirements + UX Design → `ux-designer-diziet`

Understand the problem, gather domain knowledge. Bug fixes: reproduce, identify root cause. Small features: requirements, user journey, DX impact.

**Artifact**: Brief requirements + UX notes.

### 1b. Test Case Specification → `qa-engineer-marvin`

Test case SPECIFICATIONS (not code) covering the change. Each: description, expected outcome, requirement traceability.

**Artifact**: Test case specification (brief).

### 1c. Development Plan → `architect-nagatha`

Select approach, guide code placement, ensure maintainability. Task breakdown referencing test cases.

Batch small tasks so each agent gets ≥100 lines of work within same specialization.

**Artifact**: Development plan with tasks.

## Phase 2: Implementation → `developer-bilby`

Brief each task by goal and acceptance criteria, not files or approach — Bilby investigates and designs the HOW itself (see `grand-admiral` § Development-Work Delegation). For each task:
1. Investigate, draft an implementation plan (files, approach, sequence), get coordinator sign-off before writing code
2. Write tests from Test Case Specification — must fail initially
3. Implement until tests pass
4. Self-review: deduplication, code quality, formatting, linting
5. Commit

**Pre-empt the QA audits before declaring impl done:**
1. **Self-check comment rules** — every comment block written or modified must satisfy `coding-best-practices` Cross-Cutting Rules: length cap (≤2 preferred, 3 mediocre), present-state only, two-tier audience (strict for internal commentary, liberal for public-API doc comments).
2. **Self-check duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, grep the workspace, direct dependencies (per the project's manifest — `Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, etc.), and any project-defined reference repos for an existing equivalent first. If found and publicly exported, use it. If crate-private (or language equivalent), propose promoting it. If it only partially overlaps, document the rationale for the new copy.
3. **Report rejected equivalents** — list candidates considered and rejected, one-line rationale each, in the implementation summary so QA has context.

### TDD Discipline

1. Tests derive from the Test Case Specification, not from implementation.
2. Tests must fail before implementation begins.
3. If a test matches the spec, the *code* is wrong — fix the code, not the test.

## Phase 3: QA

Run in parallel where possible:

| Agent | Focus |
|-------|-------|
| `qa-engineer-marvin` | **Tests** — execute test cases from spec, verify all pass. Marvin's full and only remit here — docs-review and dedup-audit belong to `project-reviewer-adams` below. |
| `security-engineer-smythe` | Security audit |
| `project-reviewer-adams` | Validate Development Plan fully executed, code quality — **plus two absorbed read-only passes**:<br>• **Docs review** — apply `coding-best-practices` Cross-Cutting Rules (length cap + present-state + two-tier audience) to comments and API doc comments (rustdoc, JSDoc, docstrings, godoc, etc.) introduced by the PR diff. Findings with file:line citations and proposed rewrites at `/tmp/claudius-<scope>-docs-report.md`.<br>• **Dedup audit** — for every new publicly exported function, type, trait/interface, and module in the PR, search the workspace, direct dependencies (per the project's manifest), and project-defined reference repos for equivalent functionality. Findings (high-confidence duplicates, partial overlaps, reviewed-and-rejected) with file:line citations both sides at `/tmp/claudius-<scope>-dedup-report.md`. |

Scale down agent set for truly small changes — but Marvin, Smythe, and Adams are always required (matches `grumpy-review`'s fixed core trio: security and structural/adversarial review are never optional, only their depth scales).

**Only `qa-engineer-marvin` executes the build/test/lint suite.** Smythe and Adams review via diff/read/grep and MUST NOT re-run build, test, or lint commands unless investigating a specific Marvin-reported failure — redundant compiles waste wall-clock and tokens and risk lock contention on a shared target dir. Word each spawn prompt accordingly; never leave build ownership implicit.

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

Agents default to `model: inherit`; set model per spawn (see `claudius:delegate` § Token Economy). Use `sonnet` for mechanical sub-tasks and `technical-writer-trillian`; escalate stuck or complex agents to `opus`.

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations, its severity must not increase.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL code-mutating spawned agents MUST work in an isolated git worktree — no exceptions. The `isolation` flag is unreliable (silently dropped); the coordinator pre-creates the worktree.

**Pre-flight pattern**: see `grand-admiral` § Worktree Isolation. Default is Option A (local-SHA injection, no push); Option B (push first) is the explicit fallback.

**Post-wave**: verify worktree commits, merge into the feature branch, run tests, then clean up worktrees. Push only when the user explicitly authorizes it (e.g., via `/push`, `/ci-dance`, or direct instruction) — never as an automatic step.
