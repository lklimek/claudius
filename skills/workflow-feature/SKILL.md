---
name: workflow-feature
description: "This skill should be used when the user asks to \"build a new project\", \"add a feature\", or perform a major refactoring. It runs Planning (Req→UX→Test Spec→Dev Plan) → Implementation → QA → Lessons Learned, with unattended auto-retry on failure."
---

# Feature Workflow

Use for new projects, new/fundamentally modified features, major refactoring.

Four phases, MANDATORY and SEQUENTIAL. Never skip, merge, reorder, or run phases in parallel. Within a phase, tasks and sub-phases MAY be combined or parallelized.

## Before You Start

Search project and global memories before planning or dispatching agents (MemCan MCP tools — use if available, skip silently if not):
1. `search_memories(query="<topic>", project="<repo>")` — what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — full details of relevant hits

## Unattended Operation

Runs without user interaction unless a decision is required. Do NOT pause for confirmation between phases. Accumulate reports and present a single **Final Report** when all phases complete or the workflow cannot proceed.

## Phase 1: Planning

Four sequential sub-phases, each producing an artifact consumed by the next. Sub-phases may be combined into fewer agent invocations for small scope, but the concerns must be addressed in order.

### 1a. Requirements → `ux-designer-diziet`

Personas, domain knowledge, functional/non-functional requirements, user stories, data needs & processing rules. Validate requirements against each persona.

**Artifact**: Requirements document — structured list with acceptance criteria.

### 1b. UX Design → `ux-designer-diziet`

User journeys, interaction patterns, UI mocks/wireframes, accessibility, DX planning. Derived from Requirements artifact.

**Artifact**: UX specification — journeys, mocks, interaction patterns.

### 1c. Test Case Specification → `qa-engineer-marvin`

Test case SPECIFICATIONS (not code) derived from Requirements + UX artifacts. Each: ID, description, preconditions, steps, expected outcome, requirement traceability. These define the acceptance criteria QA validates against.

**Artifact**: Test case specification document.

### 1d. Development Plan → `architect-nagatha`

System layers and responsibilities, tool/tech selection, prefer reuse, guide code placement, deployment model. Decompose into implementation tasks, each referencing the test cases it satisfies.

Batch small tasks per `delegate` § Scaling → Batching — respect specialization boundaries (don't merge frontend with backend, security with docs, or unrelated domains).

**Artifact**: Development plan with task breakdown.

## Phase 2: Implementation → `developer-bilby`

Brief each task by goal and acceptance criteria, not files or approach — Bilby investigates the codebase and designs the HOW itself (see `grand-admiral` § Development-Work Delegation). For each task:
1. Investigate, draft an implementation plan (files, approach, sequence), get coordinator sign-off before writing code
2. Write unit/integration tests from the Test Case Specification — tests MUST fail initially
3. Implement until tests pass
4. Self-review: deduplication, code quality, formatting, linting
5. Commit

**Pre-empt the QA audits before declaring impl done:**
1. **Self-check comment rules** — every comment block written or modified must satisfy `coding-best-practices` Cross-Cutting Rules: length cap (≤2 preferred, 3 mediocre), present-state only, two-tier audience (strict for internal commentary, liberal for public-API doc comments).
2. **Self-check duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, grep the workspace, direct dependencies (per the project's manifest — `Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, etc.), and any project-defined reference repos for an existing equivalent first. If found and publicly exported, use it. If crate-private (or language equivalent), propose promoting it. If it only partially overlaps, document the rationale for the new copy.
3. **Report rejected equivalents** — list candidates considered and rejected, one-line rationale each, in the implementation summary so QA has context.

Multiple Bilby agents may run in parallel on independent tasks. Use teams for shared-file tasks.

### TDD Discipline

Tests are written FIRST within each task, before implementation code.

1. **Tests derive from the Test Case Specification** (Phase 1c), not from implementation.
2. **Tests must fail before implementation begins.** A test that passes without new code is wrong or testing the wrong thing.
3. **Failures are verified against the spec.** If a test matches the Test Case Specification, the *code* is wrong — fix the code, not the test. Adjust a test only when the specification itself changed.

## Phase 3: QA

Separate agent per concern — run in parallel:

| Agent | Focus |
|-------|-------|
| `qa-engineer-marvin` | **Tests** — execute test cases from spec, verify all pass, coverage gaps. Marvin's full and only remit here — docs-review and dedup-audit belong to `project-reviewer-adams` below. |
| `security-engineer-smythe` | Security audit, dependency security |
| `ux-designer-diziet` | UX/DX audit against UX specification |
| `technical-writer-trillian` | End-user, developer, deployment docs |
| `project-reviewer-adams` | Validate Development Plan fully executed, code quality — **plus two absorbed read-only passes**:<br>• **Docs review** — apply `coding-best-practices` Cross-Cutting Rules (length cap + present-state + two-tier audience) to comments and API doc comments (rustdoc, JSDoc, docstrings, godoc, etc.) introduced by the PR diff. Findings with file:line citations and proposed rewrites at `/tmp/claudius-<scope>-docs-report.md`.<br>• **Dedup audit** — for every new publicly exported function, type, trait/interface, and module in the PR, search the workspace, direct dependencies (per the project's manifest), and project-defined reference repos for equivalent functionality. Findings (high-confidence duplicates, partial overlaps, reviewed-and-rejected) with file:line citations both sides at `/tmp/claudius-<scope>-dedup-report.md`. |

**Only `qa-engineer-marvin` executes the build/test/lint suite.** The other four review via diff/read/grep and MUST NOT re-run build, test, or lint commands unless investigating a specific Marvin-reported failure — redundant compiles waste wall-clock and tokens and risk lock contention on a shared target dir. Word each spawn prompt accordingly; never leave build ownership implicit.

**Both audits are READ-ONLY by mandate** — emphasize this in the agent prompt template. Findings go to the lead, who decides follow-up:
- Trivial fixes can land in the same PR via a separate commit
- Substantial refactors land as follow-up PRs
- Findings the lead judges as wrong-call go in a "rejected with rationale" section of the report

To skip any audit, the lead must document the reason in the QA report.

QA validates TWO things:
1. **Test Case Specification coverage** — every test case from Phase 1c passes or has a justified exception
2. **Development Plan completion** — every task from Phase 1d was implemented

No task is done until QA passes. Formatting, linting, and test passing are not optional. Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Phase 4: Lessons Learned

After QA passes, use `claudius:lessons-learned` skill to save:
- Bugs found and root causes
- Architecture/design decisions with rationale
- Patterns, anti-patterns, workarounds discovered
- Surprising behavior or non-obvious gotchas

Default to global memories unless strictly project-specific. Skip if nothing noteworthy. Report count of memories saved.

## Failure & Auto-Retry

When a phase produces MEDIUM+ findings, test failures, or incomplete coverage:

1. Prepare a **failure report**: what failed, why, which findings, severity
2. **Auto-return to the previous phase** — do NOT wait for user acceptance
3. Previous phase receives the failure report and addresses the issues
4. Re-execute the failed phase with updated artifacts
5. **Exception**: if the failure requires a USER DECISION (ambiguous requirements, conflicting constraints, scope change), pause and present options. Otherwise proceed autonomously.

### Retry Map

| Failed Phase | Returns To | Rationale |
|---|---|---|
| QA (Phase 3) | Implementation (Phase 2) | Fix code/tests to match spec |
| Implementation (Phase 2) | Dev Plan (Phase 1d) | Plan incomplete or infeasible |
| Dev Plan (Phase 1d) | Test Case Spec (Phase 1c) | Test cases missing or contradictory |
| Test Case Spec (Phase 1c) | UX Design (Phase 1b) | UX spec incomplete or ambiguous |
| UX Design (Phase 1b) | Requirements (Phase 1a) | Requirements incomplete or conflicting |

**Max 3 retries per phase.** After 3, escalate to the user with a full report of all attempts and unresolved issues.

## Final Report

Presented ONLY when all phases complete (or max retries exhausted):

- **Per-phase summary**: what was done, artifacts produced, iterations needed
- **Findings resolved**: count by severity, auto-fixed vs deferred
- **Retry log**: which phases retried, why, how resolved
- **Outstanding issues**: anything needing user attention
- **Memories saved**: count from Lessons Learned

## Model Selection

Agents default to `model: inherit`; set model per spawn (see `claudius:delegate` § Token Economy). Feature work leans `opus` for complex design and decisions; use `sonnet` for routine sub-tasks (straightforward implementation, config, docs, `technical-writer-trillian`).

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations (same meaning, possibly different agent/ID/wording), its severity must not increase — downgrade to the previous iteration's level.

## Code Deduplication

Include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.

## Multi-Agent Coordination

For phases with multiple agents on shared files, coordinate via named spawns + `SendMessage` claim/completion broadcasts to prevent duplicate work and conflicts. See `grand-admiral` § Spawning and `ci-dance` § Inter-Stream Communication.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL code-mutating spawned agents MUST work in an isolated git worktree — no exceptions. The `isolation` flag is unreliable (silently dropped); the coordinator pre-creates the worktree.

**Pre-flight pattern**: see `grand-admiral` § Worktree Isolation. Default is Option A (local-SHA injection, no push); Option B (push first) is the explicit fallback.

**Post-wave**: verify worktree commits, merge into the feature branch, run tests, then clean up worktrees. Push only when the user explicitly authorizes it (e.g., via `/push`, `/ci-dance`, or direct instruction) — never as an automatic step.
