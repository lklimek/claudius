---
name: workflow-trivial
description: "Use for typos or single-line fixes (≤20 lines). Phases: TDD → Implementation → QA → Lessons Learned."
---

# Trivial Workflow

Use for typos, single-line fixes (≤20 lines), no new dependencies/files.

## Phases

1. **TDD: Tests** — write/update tests first from requirements, verify they fail.

2. **Implementation** → `developer-bilby` — build env if needed, implement until tests pass.

3. **QA** — pass tests, formatter, linter.

4. **Lessons Learned** — if anything noteworthy was learned, save via `mindajo:persistent-memory` skill (if available). Default to global memories unless strictly project-specific. Report count of memories saved. Skip for truly trivial fixes.

## TDD Discipline

1. Tests derive from requirements, not from implementation.
2. Tests must fail before implementation begins.
3. If a test fails post-implementation and matches documented behavior, the *code* is wrong.

## QA Gate

No task is done until QA passes. Formatting, linting, and test passing are not optional.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.
