---
name: workflow-simplified
description: "Use for bug fixes or small changes (≤200 lines). Phases: Requirements → Architecture → TDD → Implementation → QA → Lessons Learned (lighter ceremony)."
---

# Simplified Workflow

Use for bug fixes, small changes (≤200 lines), small local refactorings.

Follow all phases on the first iteration. QA must always be fully executed.

## Before You Start

Search project and global memories for relevant context before planning or dispatching agents:
1. `search_memories(query="<topic>", project="<repo>")` — discover what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — read full details of relevant memories found in step 1

These are MCP tools on the MemCan server. Use them if available. Skip silently if not.

## Phases

1. **Requirements** — understand the problem, gather domain knowledge, ask user questions.

2. **Architecture** — select tools/technologies, guide code placement, ensure maintainability.

3. **TDD: Tests** (per task) → `qa-engineer` + `developer-bilby`
   Write tests from requirements and docs *before* implementation. Verify they fail.

4. **Implementation** (per task) → `developer-bilby`
   Build env → implement until tests pass → self-review → iterate.

5. **QA** → `qa-engineer` + `security-engineer` + `ux-designer` + `technical-writer` + `project-reviewer`
   Docs, integration tests, code quality, security, dependency security, UX/DX audit,
   pass tests/formatter/linter.

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

Agent frontmatter defaults apply. Use `model: "sonnet"` to override for:
- `technical-writer` — documentation is sonnet's strength
- Escalate stuck agents to `model: "opus"` for complex debugging

## Subsequent Iterations

On subsequent iterations you may use a different workflow, skip non-QA phases if appropriate,
or request specialist validation — but QA must always be fully executed.

## TDD Discipline

Tests are a dedicated workflow phase, not part of implementation.

1. **Tests derive from requirements and documentation**, not from implementation.
2. **Tests must fail before implementation begins.**
3. **Failures are verified against docs.** If the test matches documented behavior, the *code* is wrong.

## QA Gate

**Never conclude work without passing QA.**

- First iteration: all phases must complete, including full QA.
- No task is done until QA passes. Formatting, linting, and test passing are not optional.
- Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations, its severity must not increase.

## Code Deduplication

Include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

**When spawning parallel agents**, use `isolation: "worktree"` to avoid file conflicts. Pre-flight: check `git log @{upstream}..HEAD --oneline` for unpushed commits (worktrees fork from `origin`, not local branch). After each parallel wave: verify worktree commits, merge into main, run tests, then clean up.

**Single-agent phases** run directly in the working directory — no worktree overhead.
