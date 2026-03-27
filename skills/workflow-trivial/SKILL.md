---
name: workflow-trivial
description: "Use for typos or single-line fixes (≤20 lines). Same mandatory phase order (Planning→Impl→QA→LL), minimal ceremony. Auto-retry on failure."
---

# Trivial Workflow

Use for typos, single-line fixes (≤20 lines), no new dependencies/files.

Same mandatory phase order, minimal ceremony. Phases are SEQUENTIAL — never skip, merge, reorder, or run phases in parallel. Within a phase, tasks may be combined.

## Before You Start

Search project and global memories for relevant context:
1. `search_memories(query="<topic>", project="<repo>")`
2. `get_memories(memory_id="<id>")`

MemCan MCP tools. Use if available, skip silently if not.

## Phase 1: Planning (Lightweight)

Single agent invocation combining all planning concerns:

**Requirements + Test Case Spec + Dev Plan** — understand the fix, write 1-3 test case specifications (description + expected outcome), identify the change location.

No separate UX or architecture sub-phases needed for trivial fixes.

## Phase 2: Implementation → `developer-bilby`

1. Write/update tests from the test case spec — must fail initially
2. Implement until tests pass
3. Format, lint, commit

### TDD Discipline

1. Tests derive from the test case spec, not from implementation.
2. Tests must fail before implementation begins.
3. If a test matches the spec, the *code* is wrong.

## Phase 3: QA

Pass tests, formatter, linter. Verify the fix delivers the intended experience, not just passes tests.

## Phase 4: Lessons Learned

If anything noteworthy was learned, save via `claudius:lessons-learned`. Default to global memories. Skip for truly trivial fixes. Report count saved.

## Failure & Auto-Retry

1. QA fails → return to Implementation with failure report
2. Implementation fails → return to Planning with failure report
3. Do NOT wait for user acceptance unless a decision is required
4. Max 2 retries before escalating to user

## Model Selection

All phases use `model: "sonnet"`. Escalate to opus only for debugging non-obvious failures.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL spawned agents MUST use `isolation: "worktree"` — no exceptions.

**Pre-flight (blocking):** Run `git log @{upstream}..HEAD --oneline`. If unpushed commits exist OR no upstream is configured, STOP — push first, then launch agents (worktrees fork from `origin`, not local branch).

Before spawning, capture the resolved commit SHA (from `git rev-parse HEAD`), never a branch name or symbolic ref, and include `git merge --ff-only <sha>` in each agent's prompt so worktrees sync to correct base.

After each wave: verify worktree commits, merge into main, run tests, **push to remote**, then clean up. Always push after merging — unpushed merges cause stale-origin issues for subsequent waves.

**Anti-pattern:** committing locally then launching worktree agents that need those changes — worktrees won't see them until pushed.
