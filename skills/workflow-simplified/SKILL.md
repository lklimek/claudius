---
name: workflow-simplified
description: "Use for bug fixes or small changes (≤200 lines). Phases: Requirements → Architecture → TDD → Implementation → QA (lighter ceremony)."
---

# Simplified Workflow

Use for bug fixes, small changes (≤200 lines), small local refactorings.

Follow all phases on the first iteration. QA must always be fully executed.

## Phases

1. **Requirements** — understand the problem, gather domain knowledge, ask user questions.

2. **Architecture** — select tools/technologies, guide code placement, ensure maintainability.

3. **TDD: Tests** (per task) → `qa-engineer` + `developer-bilby`
   Write tests from requirements and docs *before* implementation. Verify they fail.

4. **Implementation** (per task) → `developer-bilby`
   Build env → implement until tests pass → self-review → iterate.

5. **QA** → `qa-engineer` + `security-engineer` + `ux-designer` + `technical-writer` + `project-reviewer` + `devops-engineer`
   Docs, integration tests, code quality, security, dependency security, UX/DX audit,
   pass tests/formatter/linter.

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

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations, its severity must not increase.

## Code Deduplication

Include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.
