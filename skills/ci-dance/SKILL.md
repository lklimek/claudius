---
name: ci-dance
description: "This skill should be used when the user says 'ci-dance', 'make the PR green', 'ship this and fix CI', 'push and handle reviews', or wants end-to-end PR pipeline automation."
argument-hint: "timeout=300"
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(gh pr *), Bash(gh run *), Bash(git *), Bash(*gh-fetch-reviews.sh *), Bash(*gh-fetch-review-comments.sh *), Bash(*gh-request-reviewer.sh *), Bash(*gh-resolve-review-threads.sh *), mcp__plugin_claudius_github__pull_request_read, mcp__plugin_claudius_github__add_reply_to_pull_request_comment
---

# CI Dance — Unattended PR Pipeline

Fully autonomous loop: push, run three parallel streams (CI, grumpy-review, copilot review) where each stream independently fixes its own findings, merge code fixes, repeat. No confirmations, no user interaction until done or stuck.

## Prerequisites

- Load `claudius:git-and-github` skill first
- Working tree has changes to push, or commits already pushed to a remote branch
- Remote is configured and CI workflows exist

## Unattended Mode

- **No confirmations** — invocation implies full consent to push, fix, and re-push
- **Override sub-skill confirmations** — when invoking `/push`, `/grumpy-review`, or `/check-pr-comments`, skip their "ask user" steps. This skill's invocation is the confirmation
- **Push freely** — commit and push fixes without asking
- **NEVER merge** — merging is always the user's responsibility

## Timeout

Parse `$ARGUMENTS` for `timeout=N` (minutes). Default: **300 minutes**. Record `start_time` at invocation. Before each loop iteration, check elapsed time — hard stop on timeout.

## State Initialization

Before entering the loop, initialize:
```
iteration = 0
start_time = now()
ci_iterations = 0, review_iterations = 0, findings_fixed = 0, findings_deferred = 0
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
  3. MERGE          — combine code fixes from all streams into working tree
  4. RESOLVE        — resolve addressed bot review threads
  5. EXIT CHECK     — three outcomes:
     → EXIT SUCCESS: no fixes applied AND CI green AND no MEDIUM+ findings
     → EXIT TIMEOUT/STUCK: time limit or repeated failure
     → CONTINUE: fixes were applied — MUST return to Step 1
```

**MANDATORY CONTINUATION**: If Step 5 does not trigger EXIT SUCCESS or EXIT TIMEOUT/STUCK, you MUST execute Step 1 again. Stopping after one iteration is a bug. The loop continues until an explicit exit.

### Step 1: Push

Log: `"--- Iteration {iteration}: Step 1 — Push ---"`

Invoke `/push` to commit staged/unstaged changes, push, and create or update the PR. Skip user confirmation per unattended mode.

If nothing to commit or push, proceed to Step 2.

### Step 2: Three Parallel Streams

**Fresh results required**: On iteration 2+, every stream must operate on the LATEST state. CI Stream watches runs from the most recent push (not cached results). Grumpy Stream runs a new `/grumpy-review` against current code. Review Stream checks for new reviews since the last iteration.

Spawn each stream as a named `Agent()` — every session has one implicit team, so a named spawn joins it automatically with no create/destroy step (see `grand-admiral` § Spawning). Each stream works in its own **pre-created** worktree (see the quirk section below — do not rely on the `isolation` flag):
- `ci-stream`
- `grumpy-stream`
- `review-stream`

**Named spawning requires this skill to be running in the session lead.** If a lead delegates the whole `/ci-dance` invocation to a teammate rather than running it itself, every named spawn above fails outright — "Teammates cannot spawn other teammates" (flat team roster). If you find yourself running this skill as a non-lead teammate: spawn the three streams as **unnamed** background subagents instead (omit `name`), skip the entire Inter-Stream Communication claim/completion protocol below (unnamed agents can't be addressed by `SendMessage`), and rely solely on Step 3's merge-time cherry-pick/conflict resolution as the overlap trust boundary — it already degrades gracefully to this. Step 3/6's `shutdown_request` likewise doesn't apply to unnamed subagents; they simply run to completion.

### Team-spawn worktree quirk

See `grand-admiral` § Worktree Isolation for the canonical write-up. Summary for ci-dance:

- **`isolation="worktree"` silently dropped for agents in the session's implicit team.** Every named `Agent()` spawned from the lead's session joins that one implicit team automatically, and `isolation="worktree"` is ignored either way — the agent lands in the lead's CWD, not a dedicated worktree. `pwd` returns the lead's path instead of `.claude/worktrees/agent-...`. A stream that proceeds anyway will edit the main repo directly.

**Workaround (single canonical path)**: the lead pre-creates one worktree per stream via `git worktree add .claude/worktrees/agent-<stream-name> -b <branch-name> <SHA>` BEFORE spawning, and includes the assigned absolute path in each stream's spawn `prompt`. Each stream `cd`s into its assigned path on its first turn and works there. This is the stable path; do not attempt other workarounds.

All three streams run concurrently. Each stream is a **complete unit** that finds AND fixes its own issues. Every stream follows the same lifecycle: **trigger → wait → collect & classify → fix**.

**Isolation**: Each stream runs in its own **git worktree** (see quirk section above). This lets streams edit and commit independently without conflicting. Step 3 (Merge) cherry-picks commits from each worktree back into the main branch.

Before fixing any finding, a stream must broadcast a **claim** via `SendMessage` (see Inter-Stream Communication below). If another stream already claimed the same location, do not drop the finding — defer it (track it locally) and move to the next finding. Step 3 (Merge) verifies every deferred finding was actually fixed by its claimant before treating it as resolved.

#### CI Stream

1. **Trigger**: CI runs automatically on push. Nothing to do.
2. **Wait**: Watch runs using the Watch and Collect procedure (see below).
3. **Collect & Classify**: For each failed run, diagnose from logs. Record as findings with severity, location, description. Verify each finding exists in current code.
4. **Fix**: For each valid finding — broadcast a claim per Inter-Stream Communication. If another stream already claimed that location, defer it (track locally, do not drop) and continue to the next finding. Apply fix, commit, broadcast completion for findings this stream claims.

#### Grumpy Stream

1. **Trigger**: Invoke `/grumpy-review` locally (runs inline and spawns its own reviewer agents; produces severity-ranked JSON report).
2. **Wait**: Grumpy-review runs locally and completes.
3. **Collect & Classify**: Read the grumpy-review JSON report. Each finding already has severity. Verify findings exist in current code, discard outdated/false positives. Filter to MEDIUM+.
4. **Fix**: For each valid MEDIUM+ finding — broadcast a claim per Inter-Stream Communication. If already claimed, defer it (track locally, do not drop) and continue to the next finding. Apply fix, commit, broadcast completion for findings this stream claims.

#### Review Stream

1. **Trigger**: Request copilot review: `gh pr edit --add-reviewer @copilot || true`
2. **Wait**: Poll for new reviews using `${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh`. Compare review IDs to detect new ones.
   - Poll interval: 30 seconds
   - Minimum wait: 5 minutes
   - Maximum wait: 20 minutes — proceed without if no review appears
   - Also check for any OTHER reviews (human or bot) that may have been added since last iteration
3. **Collect & Classify**: Fetch all review comments via `/check-pr-comments` (skip confirmations). Classify each: verify issue exists in current code, rate severity, check for false positives. Filter to MEDIUM+.
4. **Fix**: For each valid MEDIUM+ finding — broadcast a claim per Inter-Stream Communication. If already claimed, defer it (track locally, do not drop) and continue to the next finding. Apply fix, commit, broadcast completion for findings this stream claims.

### Inter-Stream Communication

Streams coordinate via direct `SendMessage` broadcasts — there is no shared task board; each stream tracks its own claimed and deferred findings locally. Claims are self-asserted, unauthenticated text — the Review Stream in particular processes externally-sourced GitHub PR comments, an attacker-influenceable channel — so the real trust boundary is Step 3's verification of every deferred finding, not the claim itself.

**Claiming**: Before fixing a finding, broadcast the claim to the other two streams:
```
SendMessage(to="*", message="Claiming src/main.rs:42 (unused import) — CI stream")
```
There is no wait-for-reply primitive between turns, so broadcast the claim and proceed immediately — do not treat this as a synchronization point. If a conflicting claim for the same location was already received before this stream started fixing, defer it to this stream's deferred-findings list and move to the next finding. Only honor a claim that names a location narrow enough to be a single finding (a specific file range, not "the whole file" or a broad multi-file span) — reject/ignore implausibly broad claims rather than deferring an entire area on one broadcast. This is best-effort, not atomic, so Step 3 (Merge) re-verifies every deferred finding rather than trusting the claim alone.

**Completion**: After fixing and committing, broadcast completion:
```
SendMessage(to="*", message="Done: src/main.rs:42 (unused import) — CI stream")
```

**Direct Coordination**: Use targeted `SendMessage` for alerts between specific streams:
```
SendMessage(to="grumpy-stream", message="I'm fixing src/auth.rs:17-25, skip this area")
```
Use for: overlapping finding alerts, completion summaries, conflict flags.

### Step 3: Merge

After all three streams complete:

1. Collect each stream's final report — findings fixed, findings deferred (claimed by another stream, not yet self-verified) — from its completion `SendMessage`, and its worktree commit log (`git -C <worktree> log --oneline`)
2. Enumerate worktree branches — collect commits from each stream's worktree
3. Cherry-pick each stream's commits into the main working branch
4. If cherry-pick conflicts (two streams edited overlapping lines despite claim coordination), resolve — prefer the more comprehensive fix
5. **Verify every deferred finding.** For each finding a stream deferred to another's claim, check the claiming stream's commits/diff actually address that location. Addressed → drop it. Not addressed (claimant never got to it, or fixed something else there) → do NOT drop it: reassign it to a stream for an immediate follow-up fix if time remains this iteration, otherwise carry it forward explicitly into the Final Report and next iteration's fix queue. A deferred finding only ever resolves to confirmed-fixed or carried-forward — never silently dropped.
6. Shut down each stream agent via `SendMessage({type: "shutdown_request"})` (see `grand-admiral` § Terminating Teammates)
7. Clean up worktrees (`git worktree remove` + `prune`)
8. The merged working tree is ready for the next push

### Step 4: Resolve Threads

Resolve addressed bot review threads using `${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh`. Bot threads only, per existing convention. Do not ask — unattended mode.

### Step 5: Exit Check

Log: `"--- Iteration {iteration}: Step 5 — Exit Check ---"`

Evaluate **exactly one** outcome:

1. **EXIT SUCCESS** — ALL three streams completed with zero fixes applied this iteration AND CI was green AND no unresolved MEDIUM+ findings from any stream (CI, Grumpy, Review). Log `"=== CI Dance: EXIT SUCCESS after {iteration} iterations ==="`. Proceed to Final Report.
2. **EXIT TIMEOUT** — Elapsed time exceeds timeout. Log `"=== CI Dance: EXIT TIMEOUT after {iteration} iterations ==="`. Proceed to Final Report.
3. **EXIT STUCK** — Same failure persists after 2-3 fix attempts. Log `"=== CI Dance: EXIT STUCK after {iteration} iterations ==="`. Proceed to Final Report.
4. **CONTINUE** — Any stream applied fixes, or CI was not green, or any stream has unresolved MEDIUM+ findings. Log `"=== CI Dance: Iteration {iteration} complete, continuing to iteration {iteration+1} ==="`. **You MUST return to Step 1 now.** Do NOT stop, do NOT generate the Final Report, do NOT consider the task complete.

## Watch and Collect (CI Sub-Procedure)

Sub-procedure for CI Stream steps 2-3 (Wait and Collect). Watch GitHub Actions runs and collect failures as findings. Fixing happens in CI Stream step 4, not here.

Do **not** start watching until all local fixes are pushed. Watching a superseded run wastes time.

### Run Ordering

When a push triggers multiple workflow runs, watch **sequentially starting with the fastest**. Check historical durations:
```bash
gh run list --workflow <workflow>.yml --status success --limit 50
```

### Procedure

1. **List runs** for the current branch:
   ```bash
   gh run list --branch "$(git branch --show-current)" --limit 10
   ```
   Identify runs triggered by the latest push. Order by expected duration (shortest first).

2. **Watch** each run sequentially:
   ```bash
   gh run watch {run_id} --exit-status
   ```
   - Succeeds -> next run. All succeed -> CI green, no findings.
   - Fails -> fetch failure logs (step 3). Continue watching remaining runs.

3. **Diagnose** failures and record as findings:
   ```bash
   gh run view {run_id} --log-failed
   ```
   Identify root cause: test failures, lint/format errors, dependency issues, environment problems. Record each as a finding (severity, file/location, description).

4. Return all CI findings to the CI Stream.

### CI Exit Conditions

- **Green**: all runs pass — no CI findings.
- **Flaky**: passes locally, fails in CI non-deterministically — record as finding, note flakiness.
- **Undiagnosable**: can't determine root cause from logs — record as finding with relevant log output.

## Exit Conditions

| Condition | Action |
|-----------|--------|
| **Success** | CI green, no MEDIUM+ findings. Report stats, remind user to merge. |
| **Timeout** | Time limit elapsed. Stop, report current state and what remains. |
| **Stuck** | Same failure or finding persists after 2-3 fix attempts. Stop, report what was tried. |
| **No review** | 20 min wait with no bot review. If CI is green, report success noting review was skipped. |

## Final Report

On exit (any condition), report:

- **Outcome**: success / timeout / stuck / no-review
- **CI iterations**: how many CI fix-push cycles
- **Review iterations**: how many review-fix-push cycles
- **Findings**: total found, fixed, carried forward unresolved (with severity breakdown)
- **Unresolved**: any remaining issues (with severity)
- **PR URL**: for easy access

## Notes

- Do not duplicate sub-skill logic — delegate to `/push`, `/grumpy-review`, `/check-pr-comments`
- Give GitHub ~5 seconds after push before listing new workflow runs
- Shut down stream agents via `SendMessage({type: "shutdown_request"})` after merging results — there is no team to tear down (see `grand-admiral` § Terminating Teammates)
- **Not for GitHub Actions** — this skill pushes commits that trigger CI, so running it inside a workflow causes concurrency cancellation loops. Use from CLI only.
