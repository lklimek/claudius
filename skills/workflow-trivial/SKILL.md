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
   - **Pre-empt the QA audits before declaring impl done:**
     1. **Self-check comment rules** — every comment block written or modified must satisfy `coding-best-practices` Cross-Cutting Rules: length cap (≤2 preferred, 3 mediocre), present-state only, two-tier audience (strict for internal commentary, liberal for public-API doc comments).
     2. **Self-check duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, briefly grep the workspace, direct dependencies (per the project's manifest — `Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, etc.), and any project-defined reference repos for an existing equivalent before rolling a new one. If found and publicly exported, use it. If crate-private (or language equivalent), propose promoting it. If only partially overlaps, document the rationale for the new copy.
     3. **Report rejected equivalents** — list any candidate equivalent considered and rejected, with one-line rationale, in the implementation summary so QA has context.
3. Format, lint, commit

### TDD Discipline

1. Tests derive from the test case spec, not from implementation.
2. Tests must fail before implementation begins.
3. If a test matches the spec, the *code* is wrong.

## Phase 3: QA

Pass tests, formatter, linter. Verify the fix delivers the intended experience, not just passes tests.

One READ-ONLY pass via `qa-engineer-marvin` (NO code edits — findings go to the lead):

- **Tests** — execute the test case(s) from the spec, verify they pass, flag coverage gaps. This is Marvin's full and only remit in every workflow now; the former Docs-review and Dedup-audit passes moved to `project-reviewer-adams`'s code-quality remit (see `workflow-feature`/`workflow-simplified`) — but see the omission note below for why they don't apply here.

Findings go to the lead, who decides follow-up:
- Trivial fixes can land in the same PR via a separate commit
- Substantial refactors land as follow-up PRs
- Findings the lead judges as wrong-call go in a "rejected with rationale" section of the report

**`project-reviewer-adams` omission:** workflow-trivial omits `project-reviewer-adams` entirely — including its now-expanded code-quality remit (docs-review, dedup-audit, structural/idiom consistency absorbed from `developer-bilby`'s former review role) — because trivial scope (≤20 lines, typo fixes, single-line bug repairs) does not warrant a full project-reviewer pass. At this scope, Bilby's own Phase 2 self-checks (comment-hygiene, duplication grep — see above) are the sole safeguard for those two concerns, backstopped by merge-time review. If the change starts smelling like ≥20 lines, touches multiple files, or genuinely needs an independent docs/dedup check, escalate to `workflow-simplified` instead, where Adams runs those passes.

## Phase 4: Lessons Learned

If anything noteworthy was learned, save via `claudius:lessons-learned`. Default to global memories. Skip for truly trivial fixes. Report count saved.

## Failure & Auto-Retry

1. QA fails → return to Implementation with failure report
2. Implementation fails → return to Planning with failure report
3. Do NOT wait for user acceptance unless a decision is required
4. Max 2 retries before escalating to user

## Model Selection

Agents default to `model: inherit`; trivial work sets `model: "sonnet"` on every spawn, escalating to `opus` only for debugging non-obvious failures.

## Code Deduplication

Verify the change doesn't introduce or miss existing duplication.

## Commit Discipline

Agents must commit all changes before exiting — uncommitted work cannot be merged.

ALL code-mutating spawned agents MUST work in an isolated git worktree — no exceptions. The `isolation` flag is unreliable (silently dropped); the coordinator pre-creates the worktree (see Pre-flight below).

**Pre-flight pattern**: see `grand-admiral` skill — Worktree Isolation. Default is Option A (local-SHA injection, no push); Option B (push first) is the explicit fallback.

**Post-wave**: verify worktree commits, merge into the feature branch, run tests, then clean up worktrees. Push only when the user explicitly authorizes it (e.g., via `/push`, `/ci-dance`, or direct instruction) — never push as an automatic step.
