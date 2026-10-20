---
name: review
description: "Use for code review, checking a change against requirements, or choosing basic versus full review. Basic (default) uses one strong reviewer for requirements and all execution paths; full invokes grumpy-review. For GitHub PR context and publication, use review-pr."
---

# Review

## Modes

- **Basic** (default, including an unspecified “review”): exactly one independent, high-capability reviewer. Verify requirements and all execution paths through the changed code, regardless of diff size.
- **Full** (explicit “full review” or `grumpy-review`): invoke [grumpy-review](../grumpy-review/SKILL.md). It adds independent security, structural, and adversarial passes to the same coverage baseline. Never downgrade a full review because the diff is small.

Arguments: `[basic|full] [scope]`. Scope defaults to changes against the repository's base branch, including working-tree and untracked changes when reviewing local work. Record the compared refs/commit and local changes. PR wrappers supply an exact PR scope.

## Basic workflow

1. Gather the user's requirements, acceptance criteria, relevant specs, and changed files. Carry the caller's Context Digest verbatim when supplied (`review-pr` § Context Digest). Mark missing requirements as unknown; never infer intended behavior solely from the implementation. Fix one collision-resistant scratch directory (or reuse the caller's), and assign findings/coverage paths before dispatch.
2. Load [delegate](../delegate/SKILL.md), then dispatch **one** generic worker with a strong available reasoning model at high effort where supported (Claude: Opus; Codex: a high-capability model available in the current session). Select independently of the author's model; never substitute a lightweight model for a small diff. Give it the requirements, scope, this skill's **Reviewer pass**, and absolute paths to the references below. A worker assigned this pass must not dispatch another reviewer or re-enter mode selection.
3. If independent workers are unavailable, report that limitation; do not describe an author self-review as an independent basic review. A host-imposed budget does not permit sampling paths and calling the review complete.
4. Collect the findings and coverage artifact, verify that every requirement and changed symbol is accounted for, and assemble the v4 report using `grumpy-review` §5 (report assembly only, no specialist dispatch). Supply the single producer file, plus caller-supplied files such as Pass C, to `prepare`. Always write `report.json`, even with no findings, and include the coverage status in the executive summary. An incomplete pass cannot receive a clean/complete verdict.

Review is read-only for production files. Put any verification tests in a scratch copy or isolated worktree. Return fixes as recommendations.

## Reviewer pass

Load [coding-best-practices](../coding-best-practices/SKILL.md), [report-format](../report-format/SKILL.md), and [severity](../severity/SKILL.md). Read [execution-paths.md](references/execution-paths.md) before inspecting source; it is the shared requirements and path-coverage contract for both modes.

- Verify each requirement against the live implementation and observable behavior. Include happy paths, failures, boundaries, state changes, and interactions with unchanged code.
- Read the full changed functions and affected callers/callees, not just diff hunks. Follow the shared contract without function-count, depth, caller-count, or time sampling.
- Run relevant tests and lints when practical; construct concrete counterexamples for suspected defects. A passing test does not replace path tracing. Record commands, results, and anything not executable.
- For shared state, locks, tasks, or channels, enumerate access paths and reason through interleavings, lock order, cancellation, and retries; use race/stress tools where available.
- Scan user-visible strings for misleading or alarming errors and apply the UX/DX lens.
- For security-relevant code, load the language pitfalls from [security-best-practices](../security-best-practices/SKILL.md); its full security-audit pass applies only when assigned.
- Write a producer array per `report-format` to the assigned findings file, including `[]` when clean. Write the coverage artifact required by the shared contract even when there are no findings. Run `scripts/consolidate_reports.py gate <findings-file>` from the resolved plugin root.

## Specialist passes

Full-review workers read [specialist-passes.md](references/specialist-passes.md) for the assigned **Adams** (structural) or **Marvin** (requirements/correctness) pass. These are names for perspectives, not custom agent types. The full-review coordinator owns allocation and report assembly; workers never invoke the full workflow.
