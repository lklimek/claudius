---
name: workflow-trivial
description: "Use for typos or single-line fixes (≤20 lines). Phases: TDD → Implementation → QA → Lessons Learned."
---

# Trivial Workflow

Use for typos, single-line fixes (≤20 lines), no new dependencies/files.

## Before You Start

Search project and global memories for relevant context before planning or dispatching agents:
1. `search_memories(query="<topic>", project="<repo>")` — discover what past sessions learned about this area
2. `get_memories(memory_id="<id>")` — read full details of relevant memories found in step 1

These are MCP tools on the MemCan server. Use them if available. Skip silently if not.

## Phases

1. **TDD: Tests** — write/update tests first from requirements, verify they fail.

2. **Implementation** → `developer-bilby` — build env if needed, implement until tests pass.

3. **QA** — pass tests, formatter, linter.

4. **Lessons Learned** — if anything noteworthy was learned, save via `claudius:lessons-learned` skill (if available). Default to global memories unless strictly project-specific. Report count of memories saved. Skip for truly trivial fixes.

## Model Selection

All phases use `model: "sonnet"`. Trivial fixes don't need deep reasoning.
Escalate to opus only for debugging non-obvious test failures.

## TDD Discipline

1. Tests derive from requirements, not from implementation.
2. Tests must fail before implementation begins.
3. If a test fails post-implementation and matches documented behavior, the *code* is wrong.

## QA Gate

No task is done until QA passes. Formatting, linting, and test passing are not optional.
Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL spawned agents MUST use `isolation: "worktree"` — no exceptions.

**Pre-flight (blocking):** Run `git log @{upstream}..HEAD --oneline`. If unpushed commits exist OR no upstream is configured, STOP — push first, then launch agents (worktrees fork from `origin`, not local branch).

Before spawning, capture the resolved commit SHA (from `git rev-parse HEAD`), never a branch name or symbolic ref, and include `git merge --ff-only <sha>` in each agent's prompt so worktrees sync to correct base.

After each wave: verify worktree commits, merge into main, run tests, **push to remote**, then clean up. Always push after merging — unpushed merges cause stale-origin issues for subsequent waves.

**Anti-pattern:** committing locally then launching worktree agents that need those changes — worktrees won't see them until pushed.
