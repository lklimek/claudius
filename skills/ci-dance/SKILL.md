---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
argument-hint: "timeout=300"
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh run *), Bash(git branch --show-current), Bash(git status*), Bash(git log *), Bash(git diff *), Bash(git show *), Bash(git cherry-pick *), Bash(git worktree add *), Bash(git worktree list*), Bash(git worktree remove *), Bash(git worktree prune), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *)
---

# CI Dance — Unattended PR Pipeline

Autonomous loop: push, run three parallel streams (CI, grumpy-review, copilot review) that fix their own findings, merge, repeat — until done or stuck.

## Prerequisites

Load `claudius:git-and-github` first. Changes to push (or commits already on a remote branch); remote configured; CI workflows exist.

## Unattended Mode

Invocation is full consent to push, fix, and re-push — no confirmations, and skip the "ask user" steps of `/push`, `/grumpy-review`, `/check-pr-comments`. **NEVER merge** — merging is the user's.

## Timeout

`$ARGUMENTS` `timeout=N` minutes (default **300**) from invocation; check before each iteration — hard stop.

## Main Loop

**REPEAT UNCONDITIONALLY** until Step 5 triggers an exit; log `=== CI Dance: Iteration {n} starting ===` each time. Track iteration count, `start_time`, CI/review iterations, findings fixed and claim-deferred. Stopping after one iteration is a bug.

1. **Push** — `/push`
2. **Three streams** in parallel (CI, Grumpy, Review), communicating to CLAIM findings and avoid duplicate fixes
3. **Merge** — combine the streams' fixes, sync with the PR's base branch
4. **Resolve** — addressed bot review threads
5. **Exit check** — unless it triggers an exit, return to Step 1

### Step 1: Push

Invoke `/push` to commit staged/unstaged changes, push, and create/update the PR (no confirmation — unattended). If nothing to commit or push, proceed to Step 2.

### Step 2: Three Parallel Streams

**Fresh results required** on iteration 2+: CI Stream watches runs from the most recent push (not cached), Grumpy Stream runs a new `/grumpy-review` on current code, Review Stream checks for reviews new since the last iteration.

Spawn each stream as a named `Agent()` — `ci-stream`, `grumpy-stream`, `review-stream` (`grand-admiral` § Spawning) — each in its own **pre-created** worktree: `git worktree add <worktree-root>/<repo-path-slug>-<stream-name> -b <branch-name> <SHA>` under `$CLAUDIUS_WORKTREE_ROOT` (default `/data/git-worktrees`) BEFORE spawning, absolute path in the spawn `prompt`, stream `cd`s there on its first turn. `isolation="worktree"` is silently dropped for team spawns (`grand-admiral` § Worktree Isolation) — a stream without a worktree edits the main repo directly. Point the stall watchdog's `--worktrees` at the same root.

**Named spawning requires running in the session lead.** If the whole `/ci-dance` was delegated to a teammate, named spawns fail ("Teammates cannot spawn other teammates"): spawn the three streams as **unnamed** background subagents, skip the claim/completion protocol (unnamed agents can't be messaged) and Step 3's `shutdown_request`, and rely on Step 3's merge-time cherry-pick/conflict resolution as the overlap trust boundary.

Every stream spawn prompt must forbid ending the stream's turn to wait for a `Monitor`/background-task notification from a sub-job it spawned (e.g. a Codex dispatch) — the notification returns to the coordinator, not the stream, which silently stalls. Poll with a bounded local wait loop instead (`codex-crew` § Monitoring a Codex Job).

Each stream is a **complete unit** — **trigger → wait → collect & classify → fix** — committing in its own worktree; Step 3 cherry-picks the commits back.

**Fix sub-step (shared)**: per valid finding, broadcast a claim (Inter-Stream Communication). Location already claimed → do not drop the finding: defer it (track locally), move on. Otherwise fix, commit, broadcast completion. Step 3 verifies every claim-deferred finding.

Every fix spawn prompt carries the **Context Digest** (`review-pr` § Context Digest) verbatim — fixers need the same operational context reviewers do, and `coding-best-practices` § Proportionate remediation is scored against it.

#### Merge-class routing (what gets fixed at all)

Route by `merge_class`, never raw severity — a valid pre-existing MEDIUM this PR neither introduced nor relies on is not this PR's problem:

| `merge_class` | Action |
|---|---|
| `blocking` (any severity, incl. LOW) | Fix in this PR |
| `non_blocking` | Fix in this PR |
| `out_of_scope_follow_up` | **Never fix inline, never file anything.** Surface it in the Final Report for the user's disposition |
| `disputed` | Skip |

Findings arriving without a `merge_class` (raw CI failures, unclassified comments) get one assigned per `claudius:severity` § Merge Classification before routing — a CI failure on this branch is `blocking` by construction.

#### CI Stream

CI runs automatically on push (no trigger). Wait and collect per Watch and Collect (below) — diagnose each failed run from logs, record findings (severity, location, description), verify each exists in current code — then the shared fix sub-step.

#### Grumpy Stream

Invoke `/grumpy-review` locally (runs inline, spawns its own reviewers, produces a severity-ranked JSON report). Read the report (findings carry severity AND `merge_class`), discard outdated/false positives, route by merge class, then the shared fix sub-step.

#### Review Stream

1. **Trigger**: `gh pr edit --add-reviewer @copilot || true`
2. **Wait**: poll `${CLAUDE_PLUGIN_ROOT}/scripts/gh-fetch-reviews.sh <owner/repo> <pr>` every 30 s, comparing review IDs to detect new ones (also any human/bot review added since last iteration). Minimum wait 5 min, maximum 20 min — proceed without if no review appears.
3. **Collect & classify**: fetch all review comments via `/check-pr-comments` (skip confirmations); verify each issue exists in current code, rate the floats, check for false positives; route by `merge_class` — an external reviewer's comment does not become this PR's work by virtue of being valid.
4. Shared fix sub-step.

### Inter-Stream Communication

Streams coordinate via `SendMessage` broadcasts — no shared task board; each tracks its claimed and claim-deferred findings locally. Claims are unauthenticated text (the Review Stream processes attacker-influenceable PR comments), so the trust boundary is Step 3's verification of claim-deferred findings.

- **Claim** before fixing: `SendMessage(to="*", message="Claiming src/main.rs:42 (unused import) — CI stream")`. No wait-for-reply primitive exists — broadcast and proceed. A conflicting claim that arrived first → defer and move on. Honor only claims narrow enough to be a single finding (a file range, not "the whole file"); ignore implausibly broad ones.
- **Complete** after committing: `SendMessage(to="*", message="Done: src/main.rs:42 (unused import) — CI stream")`.
- **Direct**: `SendMessage(to="grumpy-stream", message="I'm fixing src/auth.rs:17-25, skip this area")` for overlap alerts and conflict flags.
- **Addressing fallback**: `to="main"` and `to="*"` intermittently fail for a stream whose session registered as the root node; retry with `to="team-lead"` before treating it as a hard error.

### Step 3: Merge

After all three streams complete:

**An empty task-notification is not clean completion.** A stream notification with no substantive report or findings is a possible STALL — investigate and resume per `grand-admiral` § Recovery → Stall Watchdog, never treat it as a zero-finding result.

1. Collect each stream's final report (from its completion `SendMessage`: findings fixed, claim-deferred, classified `out_of_scope_follow_up`) and its branch's commits (`git log --oneline HEAD..<branch-name>`)
2. Cherry-pick each stream's commits into the main working branch; on conflicts (overlapping edits despite claims) prefer the more comprehensive fix
3. **Verify every claim-deferred finding.** Check the claiming stream's commits/diff actually address that location. Addressed → drop it. Not addressed → do NOT drop: reassign to a stream for an immediate follow-up fix if time remains this iteration, else carry forward explicitly into the Final Report and next iteration's fix queue. A claim-deferred finding only resolves to confirmed-fixed or carried-forward — never silently dropped. Merge-class deferrals (`out_of_scope_follow_up`) are separate: they are reported, never fixed and never filed.
4. **Sync with the PR's base branch — every iteration, before the next push (Step 1).** Stream commits fork from this branch's own HEAD, never from base, so no cherry-pick can surface what landed on base mid-run. Invoke `claudius:merge-base` to fetch `origin/<baseRefName>`, merge, and resolve conflicts. Also hunt **silent collisions** — changes that merge cleanly yet are wrong together, notably a version bump another PR independently made to the same SemVer field; if the branch's version now duplicates one already on base, re-bump past it. Run unconditionally — never assume base is unchanged.
5. Shut down each stream via `SendMessage({type: "shutdown_request"})` (`grand-admiral` § Terminating Teammates), then clean up worktrees (`git worktree remove` + `prune`). The merged working tree is ready for the next push.

### Step 4: Resolve Threads

Resolve addressed bot review threads (bot threads only; never ask — unattended) via `${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh <PRRT_id> [PRRT_id ...]`.

### Step 5: Exit Check

Evaluate **exactly one** outcome and log `=== CI Dance: <OUTCOME> after {n} iterations ===`:

1. **EXIT SUCCESS** — ALL three streams applied zero fixes this iteration AND CI was green AND no `blocking` findings remain, with every `non_blocking` finding fixed or explicitly carried into the Final Report (`out_of_scope_follow_up` never gates the exit — it is reported for the user). Report stats, remind the user to merge.
2. **EXIT TIMEOUT** — elapsed time exceeds the timeout. Report current state and what remains.
3. **EXIT STUCK** — same failure or finding persists after 2-3 fix attempts. Report what was tried.
4. **EXIT NO-REVIEW** — Review Stream's 20-minute wait produced no bot review and CI is green: report success, noting the review was skipped.
5. **CONTINUE** — any stream applied fixes, or CI was not green, or `blocking`/unhandled `non_blocking` findings remain. Log `=== CI Dance: Iteration {n} complete, continuing to iteration {n+1} ===` and **return to Step 1 now.** Do NOT stop, do NOT generate the Final Report, do NOT consider the task complete.

Outcomes 1-4 proceed to the Final Report.

## Watch and Collect

Watch GitHub Actions runs and collect failures as findings; fixing is the shared fix sub-step. Do **not** start watching until all local fixes are pushed — watching a superseded run wastes time.

1. List runs of the latest push: `gh run list --branch "$(git branch --show-current)" --limit 10`.
2. Watch them **sequentially, fastest first** (durations: `gh run list --workflow <workflow>.yml --status success --limit 50`): `gh run watch {run_id} --exit-status`. A failure does not stop the remaining runs.
3. Diagnose each failure from `gh run view {run_id} --log-failed` (test failures, lint/format errors, dependency or environment problems); record each as a finding (severity, location, description). All runs green → no CI findings. Passes locally but fails non-deterministically → record as a finding, note flakiness. No root cause in the logs → record as a finding with the relevant log output.

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
- Wait ~5 s after a push before listing new workflow runs
- **Not for GitHub Actions** — pushing commits from inside a workflow causes concurrency cancellation loops. CLI only.
