---
name: workflow-feature
description: "Use for new projects, features, or major refactoring. Phases: Requirements → Architecture → TDD → Implementation → QA."
---

# Feature Workflow

Use for new projects, new/fundamentally modified features, major refactoring.

Follow all phases on the first iteration. Don't skip any phase.
Decompose phases into smaller tasks when useful.
Match agents to phases by their frontmatter descriptions.

## Phases

1. **Requirements** → `business-domain-analyst` + `ux-designer`
   Personas, domain knowledge, functional/non-functional requirements, user stories,
   data needs & processing rules, user journey, DX planning, UI mocks. Validate per persona. Iterate.

2. **Architecture** → `architect` + `devops-engineer`
   System layers and responsibilities (trace every layer), tool/tech selection,
   prefer reuse, guide code placement, deployment model, work decomposition into tasks.

3. **TDD: Tests** (per task) → `qa-engineer` + `developer-bilby`
   Write tests from requirements and docs *before* implementation. Verify they fail (no implementation yet).
   Tests encode expected behavior — they are the executable spec.

4. **Implementation** (per task) → `developer-bilby`
   Build env → implement until tests pass → self-review → iterate.

5. **QA** → `qa-engineer` + `security-engineer` + `ux-designer` + `technical-writer` + `project-reviewer` + `devops-engineer`
   Docs (end-user/developer/deployment), integration tests, code quality, security,
   dependency security, UX/DX audit, pass tests/formatter/linter.

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

## Severity & Iteration

Severity levels (via `claudius:severity` skill): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Iterate until no issues above LOW remain.

**Severity inflation guard:** if a finding reappears across iterations (same meaning, possibly different agent/ID/wording), its severity must not increase. Downgrade to the previous iteration's level.

## Code Deduplication

Every workflow must include a deduplication pass — scan for duplicated logic, extract shared helpers, eliminate copy-paste. Do this during Implementation self-review and QA code quality checks.
