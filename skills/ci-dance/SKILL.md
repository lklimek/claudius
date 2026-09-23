---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
argument-hint: "timeout=300"
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh run *), Bash(git *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(*gh-resolve-review-threads.sh *), Bash(*gh-list-review-threads.sh *), Bash(*gh-post-review-reply.sh *)
---

# CI Dance — Unattended PR Pipeline

Fully autonomous loop: push, run three parallel streams (CI, grumpy-review, copilot review) that each fix their own findings, merge fixes, repeat — until done or stuck.

## Prerequisites

Load `claudius:git-and-github` first. Changes to push (or commits already on a remote branch); remote configured; CI workflows exist.

## Unattended Mode

Invocation is full consent to push, fix, and re-push — no confirmations, and skip the "ask user" steps of `/push`, `/grumpy-review`, `/check-pr-comments`. **NEVER merge** — merging is the user's.

## Timeout

Parse `$ARGUMENTS` for `timeout=N` (minutes). Default: **300**. Record `start_time` at invocation; check elapsed time before each iteration — hard stop on timeout.

## State Initialization

Before the loop:
```
iteration = 0
start_time = now()
ci_iterations = 0, review_iterations = 0, findings_fixed = 0, findings_claim_deferred = 0
```

## Main Loop

**REPEAT UNCONDITIONALLY** until an exit condition in Step 5 explicitly triggers EXIT:

```
  iteration += 1
  Log: "=== CI Dance: Iteration {iteration} starting ==="

  1. PUSH           — /push: commit, push, create/update PR
  2. THREE STREAMS  — run in parallel, each is COMPLETE: trigger → wait → collect & classify → FIX
     ├── CI Stream       — watch NEW runs from LATEST push → diagnose → fix
     ├── Grumpy Stream   — FRESH /grumpy-review on current code → fix
     └── Review Stream   — request copilot + check for NEW reviews → fix
     ↕ Streams communicate to CLAIM findings and avoid duplicate fixes
  3. MERGE          — combine code fixes from all streams, then sync with the PR's base branch
  4. RESOLVE        — resolve addressed bot review threads
  5. EXIT CHECK     — three outcomes:
     → EXIT SUCCESS: no fixes applied AND CI green AND no blocking/unfixed non_blocking findings
     → EXIT TIMEOUT/STUCK: time limit or repeated failure
     → CONTINUE: fixes were applied — MUST return to Step 1
```

**MANDATORY CONTINUATION**: if Step 5 triggers neither EXIT SUCCESS nor EXIT TIMEOUT/STUCK, execute Step 1 again. Stopping after one iteration is a bug.

### Step 1: Push

Log: `"--- Iteration {iteration}: Step 1 — Push ---"`

Invoke `/push` to commit staged/unstaged changes, push, and create/update the PR (no confirmation — unattended). If nothing to commit or push, proceed to Step 2.

### Step 2: Three Parallel Streams

**Fresh results required** on iteration 2+: CI Stream watches runs from the most recent push (not cached results), Grumpy Stream runs a new `/grumpy-review` against current code, Review Stream checks for reviews new since the last iteration.

Spawn each stream as a named `Agent()` — `ci-stream`, `grumpy-stream`, `review-stream` (`grand-admiral` § Spawning) — each in its own **pre-created** worktree: `git worktree add <worktree-root>/<repo-path-slug>-<stream-name> -b <branch-name> <SHA>` under `$CLAUDIUS_WORKTREE_ROOT` (default `/data/git-worktrees`) BEFORE spawning, absolute path in the spawn `prompt`, stream `cd`s there on its first turn. `isolation="worktree"` is silently dropped for team spawns (`grand-admiral` § Worktree Isolation) — a stream that proceeds without a worktree edits the main repo directly. Point the stall watchdog's `--worktrees` at the same root.

**Named spawning requires running in the session lead.** If the whole `/ci-dance` was delegated to a teammate, named spawns fail ("Teammates cannot spawn other teammates"): spawn the three streams as **unnamed** background subagents, skip the claim/completion protocol (unnamed agents can't be messaged) and Step 3's `shutdown_request`, and rely on Step 3's merge-time cherry-pick/conflict resolution as the overlap trust boundary.

Every stream spawn prompt must forbid ending the stream's turn to wait for a `Monitor`/background-task notification from a sub-job it spawned (e.g. a Codex dispatch) — the notification returns to the coordinator, not the stream, which silently stalls. Poll with a bounded local wait loop instead (`codex-crew` § Monitoring a Codex Job).

Each stream is a **complete unit** — **trigger → wait → collect & classify → fix** — editing and committing in its own worktree; Step 3 cherry-picks the commits back.

**Fix sub-step (shared by all streams)**: for each valid finding — broadcast a claim per Inter-Stream Communication. If another stream already claimed that location, do not drop the finding: defer it (track locally) and move to the next. Otherwise apply the fix, commit, and broadcast completion. Step 3 verifies every claim-deferred finding was actually fixed by its claimant before treating it as resolved.

Every fix spawn prompt carries the **Context Digest** (`review-pr` § Context Digest) verbatim — fixers need the same operational context reviewers do, and `coding-best-practices` § Proportionate remediation is scored against it.

#### Merge-class routing (what gets fixed at all)

Route by `merge_class`, never by raw severity — a valid pre-existing MEDIUM that this PR neither introduced nor relies on is not this PR's problem:

| `merge_class` | Action |
|---|---|
| `blocking` (any severity, incl. LOW) | Fix in this PR |
| `non_blocking` | Fix in this PR |
| `out_of_scope_follow_up` | **Never fix inline, never file anything.** Surface it in the Final Report for the user's disposition |
| `disputed` | Skip |

Findings arriving without a `merge_class` (raw CI failures, unclassified comments) get one assigned per `claudius:severity` § Merge Classification before routing — a CI failure on this branch is `blocking` by construction.

#### CI Stream

1. **Trigger**: CI runs automatically on push — nothing to do.
2. **Wait**: watch runs per the Watch and Collect procedure (below).
3. **Collect & Classify**: diagnose each failed run from logs; record findings (severity, location, description); verify each exists in current code.
4. **Fix**: shared fix sub-step.

#### Grumpy Stream

1. **Trigger**: invoke `/grumpy-review` locally (runs inline, spawns its own reviewer agents, produces a severity-ranked JSON report).
2. **Wait**: runs locally to completion.
3. **Collect & Classify**: read the JSON report (findings carry severity AND `merge_class`); verify findings exist in current code, discard outdated/false positives; route by merge class per the table above.
4. **Fix**: shared fix sub-step.

#### Review Stream

1. **Trigger**: request copilot review: `gh pr edit --add-reviewer @copilot || true`
2. **Wait**: poll for new reviews via `${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh`, comparing review IDs to detect new ones.
   - Poll interval: 30 seconds; minimum wait: 5 minutes; maximum: 20 minutes — proceed without if no review appears
   - Also check for any OTHER reviews (human or bot) added since last iteration
3. **Collect & Classify**: fetch all review comments via `/check-pr-comments` (skip confirmations); verify each issue exists in current code, rate the floats, check for false positives; classify and route by `merge_class` per the table above — an external reviewer's comment does not become this PR's work by virtue of being valid.
4. **Fix**: shared fix sub-step.

### Inter-Stream Communication

Streams coordinate via `SendMessage` broadcasts — no shared task board; each tracks its claimed and claim-deferred findings locally. Claims are self-asserted, unauthenticated text (the Review Stream processes attacker-influenceable PR comments), so the real trust boundary is Step 3's verification of every claim-deferred finding.

- **Claim** before fixing: `SendMessage(to="*", message="Claiming src/main.rs:42 (unused import) — CI stream")`. No wait-for-reply primitive exists — broadcast and proceed. A conflicting claim that arrived first → defer and move on. Honor only claims narrow enough to be a single finding (a file range, not "the whole file"); ignore implausibly broad ones.
- **Complete** after committing: `SendMessage(to="*", message="Done: src/main.rs:42 (unused import) — CI stream")`.
- **Direct**: `SendMessage(to="grumpy-stream", message="I'm fixing src/auth.rs:17-25, skip this area")` for overlap alerts and conflict flags.
- **Addressing fallback**: `to="main"` and `to="*"` intermittently fail for a stream whose session registered as the root node; retry with `to="team-lead"` before treating it as a hard error.

### Step 3: Merge

After all three streams complete:

**An empty task-notification is not clean completion.** A stream notification with no substantive report or findings is a possible STALL — investigate and resume per `grand-admiral` § Recovery → Stall Watchdog, never treat it as a zero-finding result.

1. Collect each stream's final report — findings fixed, findings claim-deferred (claimed by another stream, not yet self-verified), findings classified `out_of_scope_follow_up` — from its completion `SendMessage`, plus its worktree commit log (`git -C <worktree> log --oneline`)
2. Enumerate worktree branches — collect commits from each stream's worktree
3. Cherry-pick each stream's commits into the main working branch
4. On cherry-pick conflicts (overlapping edits despite claim coordination), resolve — prefer the more comprehensive fix
5. **Verify every claim-deferred finding.** Check the claiming stream's commits/diff actually address that location. Addressed → drop it. Not addressed → do NOT drop: reassign to a stream for an immediate follow-up fix if time remains this iteration, else carry forward explicitly into the Final Report and next iteration's fix queue. A claim-deferred finding only resolves to confirmed-fixed or carried-forward — never silently dropped. Merge-class deferrals (`out_of_scope_follow_up`) are separate: they are reported, never fixed and never filed.
6. **Sync with the PR's base branch — every iteration, before the next push (Step 1).** Stream commits fork from this branch's own HEAD, never from base, so no cherry-pick can surface what landed on base mid-run. Invoke `claudius:merge-base` to fetch `origin/<baseRefName>`, merge, and resolve conflicts. Also hunt **silent collisions** — changes that merge cleanly yet are wrong together, notably a version bump another PR independently made to the same SemVer field; if the branch's version now duplicates one already on base, re-bump past it. Run unconditionally — never assume base is unchanged.
7. Shut down each stream via `SendMessage({type: "shutdown_request"})` (see `grand-admiral` § Terminating Teammates)
8. Clean up worktrees (`git worktree remove` + `prune`)
9. The merged working tree is ready for the next push

### Step 4: Resolve Threads

Resolve addressed bot review threads via `${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh`. Bot threads only, per existing convention. Do not ask — unattended mode.

### Step 5: Exit Check

Log: `"--- Iteration {iteration}: Step 5 — Exit Check ---"`

Evaluate **exactly one** outcome:

1. **EXIT SUCCESS** — ALL three streams completed with zero fixes applied this iteration AND CI was green AND no `blocking` findings remain from any stream, with every `non_blocking` finding either fixed or explicitly carried into the Final Report (`out_of_scope_follow_up` findings never gate the exit — they are reported for the user). Log `"=== CI Dance: EXIT SUCCESS after {iteration} iterations ==="`. Proceed to Final Report.
2. **EXIT TIMEOUT** — elapsed time exceeds timeout. Log `"=== CI Dance: EXIT TIMEOUT after {iteration} iterations ==="`. Proceed to Final Report.
3. **EXIT STUCK** — same failure persists after 2-3 fix attempts. Log `"=== CI Dance: EXIT STUCK after {iteration} iterations ==="`. Proceed to Final Report.
4. **CONTINUE** — any stream applied fixes, or CI was not green, or `blocking`/unhandled `non_blocking` findings remain. Log `"=== CI Dance: Iteration {iteration} complete, continuing to iteration {iteration+1} ==="`. **Return to Step 1 now.** Do NOT stop, do NOT generate the Final Report, do NOT consider the task complete.

## Watch and Collect (CI Sub-Procedure)

For CI Stream steps 2-3: watch GitHub Actions runs and collect failures as findings. Fixing happens in CI Stream step 4, not here.

Do **not** start watching until all local fixes are pushed — watching a superseded run wastes time.

### Run Ordering

When a push triggers multiple workflow runs, watch **sequentially, fastest first**. Check historical durations:
```bash
gh run list --workflow <workflow>.yml --status success --limit 50
```

### Procedure

1. **List runs** for the current branch:
   ```bash
   gh run list --branch "$(git branch --show-current)" --limit 10
   ```
   Identify runs from the latest push; order shortest-first.

2. **Watch** each run sequentially:
   ```bash
   gh run watch {run_id} --exit-status
   ```
   Succeeds → next run. All succeed → CI green, no findings. Fails → fetch failure logs (step 3), continue watching remaining runs.

3. **Diagnose** failures and record findings:
   ```bash
   gh run view {run_id} --log-failed
   ```
   Identify root cause (test failures, lint/format errors, dependency issues, environment problems); record each as a finding (severity, file/location, description).

4. Return all CI findings to the CI Stream.

### CI Exit Conditions

- **Green**: all runs pass — no CI findings.
- **Flaky**: passes locally, fails in CI non-deterministically — record as finding, note flakiness.
- **Undiagnosable**: no root cause from logs — record as finding with relevant log output.

## Exit Conditions

| Condition | Action |
|-----------|--------|
| **Success** | CI green, no `blocking` findings, every `non_blocking` fixed or carried. Report stats, remind user to merge. |
| **Timeout** | Time limit elapsed. Stop, report current state and what remains. |
| **Stuck** | Same failure or finding persists after 2-3 fix attempts. Stop, report what was tried. |
| **No review** | 20 min wait with no bot review. If CI is green, report success noting review was skipped. |

## Final Report

On exit (any condition), report:

- **Outcome**: success / timeout / stuck / no-review
- **CI iterations** and **review iterations** (fix-push cycles)
- **Findings**: total found, fixed, carried forward (severity AND merge-class breakdown)
- **Deferral candidates**: every finding classified `out_of_scope_follow_up` — filter the stream reports by `merge_class` and list each with title and location. An unattended run has no PR comment thread pulling the user's eye, so this report is the only place these surface; nothing files them (`claudius:severity` § `out_of_scope_follow_up`)
- **Unresolved**: remaining issues with severity
- **PR URL**

## Notes

- Delegate to `/push`, `/grumpy-review`, `/check-pr-comments` — never duplicate their logic
- Give GitHub ~5 seconds after a push before listing new workflow runs
- **Not for GitHub Actions** — pushing commits from inside a workflow causes concurrency cancellation loops. CLI only.
