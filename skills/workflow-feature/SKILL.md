---
name: workflow-feature
description: "Use for new projects, features, or major refactoring. Phases: Planning (Req→UX→Test Spec→Dev Plan) → Implementation → QA → Lessons Learned. Auto-retry on failure, unattended."
---

# Feature Workflow

Use for new projects, new/fundamentally modified features, major refactoring.

Four phases, MANDATORY and SEQUENTIAL. Never skip, merge, reorder, or run phases in parallel. Within a phase, tasks and sub-phases MAY be combined or parallelized as appropriate.

## Before You Start

Search project and global memories for relevant context before planning or dispatching agents:
1. `search_memories(query="<topic>", project="<repo>")` — discover what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — read full details of relevant memories found in step 1

These are MCP tools on the MemCan server. Use them if available. Skip silently if not.

## Unattended Operation

This workflow runs without user interaction unless a decision is required. Do NOT pause for confirmation between phases. Accumulate reports and present a single **Final Report** when all phases complete or the workflow cannot proceed.

## Phase 1: Planning

Four sequential sub-phases. Each produces an artifact consumed by the next. Sub-phases may be combined into fewer agent invocations when scope is small, but the concerns must still be addressed in order.

### 1a. Requirements → `ux-designer-diziet`

Personas, domain knowledge, functional/non-functional requirements, user stories, data needs & processing rules. Validate requirements against each persona.

**Artifact**: Requirements document — structured list with acceptance criteria.

### 1b. UX Design → `ux-designer-diziet`

User journeys, interaction patterns, UI mocks/wireframes, accessibility, DX planning. Derived from Requirements artifact.

**Artifact**: UX specification — journeys, mocks, interaction patterns.

### 1c. Test Case Specification → `qa-engineer-marvin`

Write test case SPECIFICATIONS (not code) derived from Requirements + UX artifacts. Each test case: ID, description, preconditions, steps, expected outcome, requirement traceability. These define the acceptance criteria that QA validates against.

**Artifact**: Test case specification document.

### 1d. Development Plan → `architect-nagatha`

System layers and responsibilities, tool/tech selection, prefer reuse, guide code placement, deployment model. Decompose work into implementation tasks. Each task references which test cases it satisfies.

Batch small tasks so each agent gets ≥100 lines of work — respect specialization boundaries (don't merge frontend with backend, security with docs, or unrelated domains).

**Artifact**: Development plan with task breakdown.

## Phase 2: Implementation → `developer-bilby`

Execute the Development Plan task by task. For each task:
1. Write unit/integration tests from the Test Case Specification — tests MUST fail initially
2. Implement until tests pass
3. Self-review: deduplication, code quality, formatting, linting
4. Commit

Multiple Bilby agents may run in parallel on independent tasks. Use teams for shared-file tasks.

### TDD Discipline

Tests are written FIRST within each task, before implementation code.

1. **Tests derive from the Test Case Specification** (Phase 1c), not from implementation.
2. **Tests must fail before implementation begins.** A test that passes without new code is either wrong or testing the wrong thing.
3. **Failures are verified against the spec.** If a test matches the Test Case Specification, the *code* is wrong — fix the code, not the test. Only adjust a test when the specification itself changed.

## Phase 3: QA

Separate agent per concern — run in parallel:

| Agent | Focus |
|-------|-------|
| `qa-engineer-marvin` | Execute test cases from spec, verify all pass, coverage gaps |
| `security-engineer-smythe` | Security audit, dependency security |
| `ux-designer-diziet` | UX/DX audit against UX specification |
| `technical-writer-trillian` | End-user, developer, deployment docs |
| `project-reviewer-adams` | Validate Development Plan fully executed, code quality |

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
5. **Exception**: if the failure requires a USER DECISION (ambiguous requirements, conflicting constraints, scope change), pause and present options. Otherwise, proceed autonomously.

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

Default to `model: "opus"` — feature work involves complex decisions.
Use `model: "sonnet"` for `technical-writer-trillian` and routine sub-tasks (straightforward implementation, config changes).

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations (same meaning, possibly different agent/ID/wording), its severity must not increase. Downgrade to the previous iteration's level.

## Code Deduplication

Include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.

## Multi-Agent Coordination

For phases with multiple agents on shared files, use teams (`TeamCreate` + `SendMessage` + Task tools) to prevent duplicate work and conflicts. See the Claudius agent's Spawning section for team patterns.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL spawned agents MUST use `isolation: "worktree"` — no exceptions.

**Pre-flight (blocking):** Run `git log @{upstream}..HEAD --oneline`. If unpushed commits exist OR no upstream is configured, STOP — push first, then launch agents (worktrees fork from `origin`, not local branch).

Before spawning, capture the resolved commit SHA (from `git rev-parse HEAD`), never a branch name or symbolic ref, and include `git merge --ff-only <sha>` in each agent's prompt so worktrees sync to correct base.

After each wave: verify worktree commits, merge into main, run tests, **push to remote**, then clean up. Always push after merging — unpushed merges cause stale-origin issues for subsequent waves.

**Anti-pattern:** committing locally then launching worktree agents that need those changes — worktrees won't see them until pushed.
