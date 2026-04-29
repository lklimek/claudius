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
     1. **Self-check comment rules** — every comment block written or modified must satisfy `coding-best-practices` Cross-Cutting Rules: length cap (≤2 preferred, 3 mediocre), present-state only, two-tier audience (strict for internal, liberal for public API rustdoc).
     2. **Self-check duplication** — for every helper, parser, signer, fetch loop, atomic-write, etc. introduced, briefly grep the workspace, direct dependencies (Cargo.toml-listed crates' public APIs), and any project-defined reference repos for an existing equivalent before rolling a new one. If found and `pub`, use it. If `pub(crate)`, propose promoting it. If only partially overlaps, document the rationale for the new copy.
     3. **Report rejected equivalents** — list any candidate equivalent considered and rejected, with one-line rationale, in the implementation summary so QA has context.
3. Format, lint, commit

### TDD Discipline

1. Tests derive from the test case spec, not from implementation.
2. Tests must fail before implementation begins.
3. If a test matches the spec, the *code* is wrong.

## Phase 3: QA

Pass tests, formatter, linter. Verify the fix delivers the intended experience, not just passes tests.

Two READ-ONLY parallel audits via `qa-engineer-marvin` (NO code edits — findings go to the lead):

- **Docs review (read-only)** — apply `coding-best-practices` Cross-Cutting Rules (length cap + present-state + two-tier audience) to all comments and rustdoc introduced by the PR diff. Emit findings with file:line citations and proposed rewrites. Report path: `/tmp/claudius-<scope>-docs-report.md`.
- **Dedup audit (read-only)** — for every new public function, type, trait, and module introduced by the PR, search the workspace, direct dependencies (Cargo.toml-listed crates' public APIs), and project-defined reference repos for equivalent functionality. Emit findings: high-confidence duplicates, partial overlaps, and reviewed-and-rejected items, each with `file:line` citations on both sides. Report path: `/tmp/claudius-<scope>-dedup-report.md`.

Findings go to the lead, who decides follow-up:
- Trivial fixes can land in the same PR via a separate commit
- Substantial refactors land as follow-up PRs
- Findings the lead judges as wrong-call go in a "rejected with rationale" section of the report

**Skip rule (workflow-trivial only):** Docs review and dedup audit MAY be skipped only when: zero comment lines added/modified (skip docs review) AND zero new public symbols introduced (skip dedup). Both conditions must be documented in the QA report.

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

**Pre-flight — pick one of two options** (canonical doctrine in `grand-admiral` skill):

**Option A (default — local-SHA injection, no push required):**
1. Capture the resolved local commit SHA: `git rev-parse HEAD` (never a branch name or symbolic ref — they resolve differently in worktrees).
2. Inject the SHA into every worktree agent's prompt: `"Your worktree may be behind local HEAD. As your FIRST action, run: git merge --ff-only <sha>"` — substitute the actual SHA.
3. This works because worktrees share the object store with the parent repo — unpushed commits ARE reachable by SHA, just not by branch ref.

**Option B (fallback — push first):**
1. Run `git log @{upstream}..HEAD --oneline`. If unpushed commits exist OR no upstream is configured, push first.
2. Worktrees then fork cleanly from `origin/<branch>`.
3. Use this option only when origin is genuinely required (cross-machine work, PR-gated CI, sharing across sessions).

**Why Option A is the default**: minimizes pushes (especially in unattended/auto mode where push approval is friction), keeps work local until ready to share, plays nicely with the global "never push without explicit permission" rule.

After each wave: verify worktree commits, merge into main, run tests, push to remote when ready to share, then clean up.
