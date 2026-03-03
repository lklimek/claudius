---
name: workflow-trivial
description: Trivial workflow — typos, ≤20 lines. Phases: TDD → Implementation → QA.
---

# Trivial Workflow

Use for typos, single-line fixes (≤20 lines), no new dependencies/files.

## Phases

1. **TDD: Tests** — write/update tests first from requirements, verify they fail.

2. **Implementation** → language developer agents — build env if needed, implement until tests pass.

3. **QA** — pass tests, formatter, linter.

## TDD Discipline

1. Tests derive from requirements, not from implementation.
2. Tests must fail before implementation begins.
3. If a test fails post-implementation and matches documented behavior, the *code* is wrong.

## QA Gate

No task is done until QA passes. Formatting, linting, and test passing are not optional.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.
