---
name: workflow-simplified
description: "This skill should be used when handling a bug fix or small-to-medium change of no more than 1000 LOC. One high-capability agent runs plan → TDD tests → implementation → self-review/self-fix end-to-end from a WHAT-not-HOW brief, unattended."
---

# Simplified Workflow

For bug fixes, small-to-medium changes, local refactorings (≤1000 LOC). One agent runs the full mini-lifecycle itself — no multi-agent phase handoffs, no separate QA pass.

## Brief: WHAT, not HOW

Give the goal, acceptance criteria, and relevant Prior Knowledge (MemCan) — never a file list or approach (`grand-admiral` § Development-Work Delegation). The agent investigates, plans, and executes.

## Model

A high-capability model — Codex Astra (`--effort high`), `opus`, or `fable`; follow any standing dev-routing preference. Not lightweight tiers: the point is trusting one agent through the whole cycle unattended.

## Single-Agent Loop

1. **Plan** — investigate, decide the approach, note it briefly before writing code.
2. **TDD** — tests first; they must fail before implementation (`coding-best-practices` TDD rules).
3. **Implement** — until tests pass.
4. **Self-review** — the full diff: correctness, edge cases, duplication, comment discipline, formatting/linting (`coding-best-practices`). General review, not `grumpy-review`.
5. **Self-fix, then repeat 4–5** until a pass finds nothing new. Cap at 5 passes — at the cap, stop and report the remainder.

Out-of-scope findings during self-review: note them in the Final Report, don't fix inline.

## Commit Discipline

Commit all changes before exiting. Code-mutating agents work in a coordinator-pre-created worktree (`grand-admiral` § Worktree Isolation, Option A default); push per § Worktree Isolation → Post-wave push.

## Stuck?

Ambiguous requirement, can't reproduce, self-fix loop caps out → surface to the coordinator/user rather than guess.

## Final Report

Approach taken, tests added, self-review passes run, fixes applied, anything left out-of-scope.
