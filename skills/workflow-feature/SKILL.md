---
name: workflow-feature
description: "This skill should be used when the user asks to \"build a new project\", \"add a feature\", or perform a major refactoring. It runs Planning (Req→UX→Test Spec→Dev Plan) → Implementation → QA → Lessons Learned, with unattended auto-retry on failure."
---

# Feature Workflow

For new projects, new or fundamentally modified features, major refactoring.

Four phases, MANDATORY and SEQUENTIAL — never skip, merge, reorder, or parallelize phases. Within a phase, tasks and sub-phases MAY be combined or parallelized.

## Before You Start

Recall prior knowledge for the area per `grand-admiral` § Session Protocol (MemCan, if available).

## Unattended Operation

No pauses for confirmation between phases unless a decision is required. Accumulate reports and present a single **Final Report** when all phases complete or the workflow cannot proceed.

## Phase 1: Planning

Four sequential sub-phases, each producing an artifact consumed by the next. Combine into fewer agent invocations for small scope, but address the concerns in order.

| Sub-phase | Agent | Produces |
|---|---|---|
| **1a. Requirements** | `ux-designer-diziet` | Requirements document with acceptance criteria — personas, domain knowledge, functional/non-functional requirements, user stories, data needs & processing rules, validated against each persona |
| **1b. UX Design** | `ux-designer-diziet` | UX specification — journeys, mocks/wireframes, interaction patterns, accessibility, DX planning; derived from 1a |
| **1c. Test Case Specification** | `qa-engineer-marvin` | Test case SPECIFICATIONS (not code) from 1a+1b: ID, description, preconditions, steps, expected outcome, requirement traceability — the acceptance criteria QA validates against |
| **1d. Development Plan** | `architect-nagatha` | System layers and responsibilities, tool/tech selection, reuse, code placement, deployment model; implementation tasks each referencing the test cases it satisfies, batched per `delegate` § Scaling (respect specialization boundaries) |

## Phase 2: Implementation → `developer-bilby`

Brief each task by goal and acceptance criteria, not files or approach — Bilby investigates and designs the HOW (`grand-admiral` § Development-Work Delegation). Per task:

1. Investigate; draft an implementation plan (files, approach, sequence); get coordinator sign-off before writing code
2. Write tests from the Test Case Specification — they MUST fail first (`coding-best-practices` TDD: tests derive from the spec, not the implementation; a failing test that matches the spec means the *code* is wrong; adjust a test only when the spec itself changed)
3. Implement until tests pass
4. Self-review: deduplication, code quality, formatting, linting
5. Commit

**Pre-empt the QA audits before declaring impl done:**
- **Comment rules** — every comment written or modified satisfies `coding-best-practices` Cross-Cutting Rules (length cap, present-state only, two-tier audience).
- **Duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, grep the workspace, direct dependencies (per the project's manifest), and any project-defined reference repos for an existing equivalent. Found and public → use it; crate-private (or equivalent) → propose promoting it; partial overlap → document the rationale for the new copy.
- **Report rejected equivalents** — candidates considered and rejected, one-line rationale each, in the implementation summary.

Multiple Bilby agents may run in parallel on independent tasks; shared-file tasks use named spawns + `SendMessage` claims (`grand-admiral` § Spawning).

## Phase 3: QA

Separate agent per concern, in parallel:

| Agent | Focus |
|-------|-------|
| `qa-engineer-marvin` | **Tests** — execute test cases from the spec, verify all pass, coverage gaps. Marvin's full and only remit here. |
| `security-engineer-smythe` | Security audit, dependency security |
| `ux-designer-diziet` | UX/DX audit against the UX specification |
| `technical-writer-trillian` | End-user, developer, deployment docs |
| `project-reviewer-adams` | Development Plan fully executed; code quality; **plus two read-only passes**: **Docs review** — `coding-best-practices` Cross-Cutting Rules applied to comments and API doc comments introduced by the diff, findings with file:line and proposed rewrites at `/tmp/claudius-<scope>-docs-report.md`; **Dedup audit** — every new public function/type/trait/module checked against the workspace, direct dependencies, and reference repos, findings (duplicates, partial overlaps, reviewed-and-rejected) with file:line both sides at `/tmp/claudius-<scope>-dedup-report.md` |

**Only `qa-engineer-marvin` executes the build/test/lint suite.** The other four review via diff/read/grep and MUST NOT re-run build, test, or lint unless investigating a specific Marvin-reported failure — say so in each spawn prompt; never leave build ownership implicit.

**Both Adams audits are READ-ONLY by mandate.** Findings go to the lead: trivial fixes land in the same PR as a separate commit; substantial refactors become follow-up PRs; wrong-call findings go in a "rejected with rationale" section. Skipping an audit requires a documented reason in the QA report.

QA validates TWO things: every test case from 1c passes or has a justified exception; every task from 1d was implemented. No task is done until QA passes. Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Phase 4: Lessons Learned

After QA passes, `claudius:lessons-learned`: bugs and root causes, decisions with rationale, patterns/anti-patterns/workarounds, surprising behavior. Global memories unless strictly project-specific. Skip if nothing noteworthy; report the count saved.

## Failure & Auto-Retry

When a phase produces MEDIUM+ findings, test failures, or incomplete coverage: prepare a **failure report** (what failed, why, which findings, severity); **auto-return to the previous phase** (no user acceptance) with the report; re-execute the failed phase with updated artifacts. **Exception**: a USER DECISION (ambiguous requirements, conflicting constraints, scope change) → pause and present options.

| Failed phase | Returns to | Rationale |
|---|---|---|
| QA (3) | Implementation (2) | Fix code/tests to match spec |
| Implementation (2) | Dev Plan (1d) | Plan incomplete or infeasible |
| Dev Plan (1d) | Test Case Spec (1c) | Test cases missing or contradictory |
| Test Case Spec (1c) | UX Design (1b) | UX spec incomplete or ambiguous |
| UX Design (1b) | Requirements (1a) | Requirements incomplete or conflicting |

**Max 3 retries per phase**, then escalate to the user with all attempts and unresolved issues.

**Severity inflation guard:** a finding reappearing across iterations (same meaning, possibly different agent/ID/wording) never rises in severity — downgrade to the previous iteration's level.

## Final Report

Only when all phases complete (or retries are exhausted): per-phase summary (done, artifacts, iterations); findings resolved by severity, auto-fixed vs deferred; retry log; outstanding issues; memories saved.

## Model Selection

Set the model per spawn (`claudius:delegate` § Token Economy) — agent frontmatter carries only a tiered fallback. Feature work leans `opus` for design and decisions; `sonnet` for routine sub-tasks (straightforward implementation, config, docs).

## Severity & Iteration

`claudius:severity` levels: CRITICAL > HIGH > MEDIUM > LOW > INFO. Iterate until no issues above LOW remain.

## Commit Discipline

Agents commit all changes before exiting. ALL code-mutating spawned agents work in an isolated git worktree pre-created by the coordinator (`grand-admiral` § Worktree Isolation — Option A default, Option B fallback; post-wave merge, test, cleanup, and push per that section).
