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

These are MCP tools on the MindOJO server. Use them if available. Skip silently if not.

## Phases

1. **TDD: Tests** — write/update tests first from requirements, verify they fail.

2. **Implementation** → `developer-bilby` — build env if needed, implement until tests pass.

3. **QA** — pass tests, formatter, linter.

4. **Lessons Learned** — if anything noteworthy was learned, save via `mindojo:lessons-learned` skill (if available). Default to global memories unless strictly project-specific. Report count of memories saved. Skip for truly trivial fixes.

## TDD Discipline

1. Tests derive from requirements, not from implementation.
2. Tests must fail before implementation begins.
3. If a test fails post-implementation and matches documented behavior, the *code* is wrong.

## QA Gate

No task is done until QA passes. Formatting, linting, and test passing are not optional.
Fixes must deliver the intended end-user and developer experience, not just pass tests.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.

## Worktree & Commit Discipline

**Pre-flight**: Before spawning worktree agents, check `git log @{upstream}..HEAD --oneline` for unpushed commits. Worktrees fork from `origin`, not the local branch — unpushed commits will be invisible to agents. Alert the user and push before proceeding.

All implementation agents (`developer-bilby`, `qa-engineer`, `devops-engineer`, `technical-writer`) run in isolated worktrees. After each agent wave:

1. Verify all worktrees have committed changes (`git worktree list` + `git status` per worktree)
2. Merge/copy changes into the main working directory
3. Run tests in main to catch integration issues
4. Clean up worktrees only after confirming changes are merged

Never skip verification — uncommitted worktree changes are invisible and will be lost on cleanup.
