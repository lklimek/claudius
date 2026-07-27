---
name: workflow-simplified
description: "This skill should be used when handling a bug fix or small-to-medium change of no more than 1000 LOC. One high-capability agent runs plan → TDD tests → implementation → self-review/self-fix end-to-end from a WHAT-not-HOW brief, unattended."
---

# Simplified Workflow

For bug fixes, small-to-medium changes, local refactorings (≤1000 LOC). One agent runs the full mini-lifecycle itself — no multi-agent phase handoffs, no separate QA pass.

## Brief: WHAT, not HOW

Give the goal, acceptance criteria, and any relevant Prior Knowledge (MemCan) — never a file list or approach (see `grand-admiral` § Development-Work Delegation). The agent investigates, plans, and executes.

## Model

Route to a high-capability model — Codex Sol (`--effort high`), `opus`, or `fable`. Follow any standing dev-routing preference for code work if one is configured. Not for lightweight tiers: the point is trusting one agent through the whole cycle unattended.

## Single-Agent Loop

1. **Plan** — investigate, decide the approach, note it briefly before writing code.
2. **TDD** — write tests first; they must fail before implementation (see `coding-best-practices` TDD rules).
3. **Implement** — until tests pass.
4. **Self-review** — review the full diff: correctness, edge cases, duplication, comment discipline, formatting/linting (see `coding-best-practices`). General review, not `grumpy-review`.
5. **Self-fix, then repeat 4–5** until a review pass finds nothing new. Cap at 5 passes — if still finding issues at the cap, stop and report the remainder rather than loop indefinitely.

Out-of-scope findings during self-review: note them in the Final Report, don't fix inline.

## Commit Discipline

Commit all changes before exiting — uncommitted work cannot be merged.

Code-mutating agents work in an isolated git worktree, coordinator pre-created (see `grand-admiral` § Worktree Isolation, Option A default). Push only when the user explicitly authorizes it.

## Stuck?

If the agent can't proceed (ambiguous requirement, can't reproduce, self-fix loop caps out) — surface to the coordinator/user rather than guessing.

## Final Report

Approach taken, tests added, self-review passes run, fixes applied, anything left out-of-scope.
