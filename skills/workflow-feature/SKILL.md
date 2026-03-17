---
name: workflow-feature
description: "Use for new projects, features, or major refactoring. Phases: Requirements → Architecture → TDD → Implementation → QA → Lessons Learned."
---

# Feature Workflow

Use for new projects, new/fundamentally modified features, major refactoring.

Follow all phases on the first iteration. Don't skip any phase.
Decompose phases into smaller tasks when useful.
Match agents to phases by their frontmatter descriptions.

## Before You Start

Search project and global memories for relevant context before planning or dispatching agents:
1. `search_memories(query="<topic>", project="<repo>")` — discover what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — read full details of relevant memories found in step 1

These are MCP tools on the MemCan server. Use them if available. Skip silently if not.

## Phases

1. **Requirements** → `ux-designer`
   Personas, domain knowledge, functional/non-functional requirements, user stories,
   data needs & processing rules, user journey, DX planning, UI mocks. Validate per persona. Iterate.

2. **Architecture** → `architect`
   System layers and responsibilities (trace every layer), tool/tech selection,
   prefer reuse, guide code placement, deployment model, work decomposition into tasks.
   Batch small tasks so each agent gets ≥100 lines of work — but respect specialization boundaries (don't merge frontend with backend, security with docs, or unrelated domains).

3. **TDD: Tests** (per task) → `qa-engineer` + `developer-bilby`
   Write tests from requirements and docs *before* implementation. Verify they fail (no implementation yet).
   Tests encode expected behavior — they are the executable spec.

4. **Implementation** (per task) → `developer-bilby`
   Build env → implement until tests pass → self-review → iterate.

5. **QA** → `qa-engineer` + `security-engineer` + `ux-designer` + `technical-writer` + `project-reviewer`
   Docs (end-user/developer/deployment), integration tests, code quality, security,
   dependency security, UX/DX audit, pass tests/formatter/linter.

6. **Lessons Learned**
   After QA passes, reflect on the task. Use `memcan:lessons-learned` skill (if available) to save:
   - Bugs found and their root causes
   - Architecture or design decisions with rationale
   - Patterns, anti-patterns, or workarounds discovered
   - Surprising behavior or non-obvious gotchas
   Default to **global memories** (omit `project` param) unless the lesson is strictly project-specific.
   Skip if nothing noteworthy was learned. Quality over quantity.
   Report how many memories were saved at the end of this phase.

## Model Selection

Default to `model: "opus"` — feature work involves complex decisions across all phases.
Use `model: "sonnet"` for `technical-writer` and routine sub-tasks (straightforward implementation, config changes).

## Subsequent Iterations

On subsequent iterations you may use a different workflow, skip non-QA phases if appropriate,
or request specialist validation — but QA must always be fully executed.

## TDD Discipline

Tests are a dedicated workflow phase, not part of implementation.

1. **Tests derive from requirements and documentation**, not from implementation. Encode expected behavior from specs, user stories, or docs.
2. **Tests must fail before implementation begins.** A test that passes without new code is either wrong or testing the wrong thing.
3. **Failures are verified against docs.** When a test fails post-implementation, check the spec — if the test matches documented behavior, the *code* is wrong. Only adjust a test when the requirement itself changed.

## QA Gate

**Never conclude work without passing QA.**

- First iteration: all phases must complete, including full QA.
- Iteration cycles: QA may be deferred between iterations, but must pass before work is considered complete.
- No task is done until QA passes. Formatting, linting, and test passing are not optional.
- Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations (same meaning, possibly different agent/ID/wording), its severity must not increase. Downgrade to the previous iteration's level.

## Code Deduplication

Every workflow must include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL spawned agents MUST use `isolation: "worktree"` — no exceptions.

**Pre-flight (blocking):** Run `git log @{upstream}..HEAD --oneline`. If unpushed commits exist OR no upstream is configured, STOP — push first, then launch agents (worktrees fork from `origin`, not local branch).

Before spawning, capture the resolved commit SHA (from `git rev-parse HEAD`), never a branch name or symbolic ref, and include `git merge --ff-only <sha>` in each agent's prompt so worktrees sync to correct base.

After each wave: verify worktree commits, merge into main, run tests, **push to remote**, then clean up. Always push after merging — unpushed merges cause stale-origin issues for subsequent waves.

**Anti-pattern:** committing locally then launching worktree agents that need those changes — worktrees won't see them until pushed.
