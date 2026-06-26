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
ci_iterations = 0, review_iterations = 0, findings_fixed = 0, findings_skipped = 0
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

Before launching streams, create a team for coordination:
```
TeamCreate(team_name="ci-dance")
```

Then spawn each stream as a named agent with `team_name: "ci-dance"`, each working in its own **pre-created** worktree (see the quirk section below — do not rely on the `isolation` flag):
- `ci-stream`
- `grumpy-stream`
- `review-stream`

### Team-spawn worktree quirk

See `grand-admiral` § Worktree Isolation for the canonical write-up. Summary for ci-dance:

- **`isolation="worktree"` silently dropped for team-spawned agents.** `Agent(team_name=..., isolation="worktree")` lands the agent in the lead's CWD, not a dedicated worktree. `pwd` returns the lead's path instead of `.claude/worktrees/agent-...`. A stream that proceeds anyway will edit the main repo directly.
- **Team context inheritance** — explanatory note, NOT a recovery path. `Agent()` calls issued from within a team-lead session that OMIT `team_name` are auto-joined to the lead's team and lose `isolation` the same way. Omitting `team_name` does not escape the team context, which is why the lead cannot rely on an in-session "spawn solo" trick — the worktree must be pre-created externally.

**Workaround (single canonical path)**: the lead pre-creates one worktree per stream via `git worktree add .claude/worktrees/agent-<stream-name> -b <branch-name> <SHA>` BEFORE spawning, and includes the assigned absolute path in each stream's spawn `prompt`. Each stream `cd`s into its assigned path on its first turn and works there. This is the stable path; do not attempt other workarounds.

All three streams run concurrently. Each stream is a **complete unit** that finds AND fixes its own issues. Every stream follows the same lifecycle: **trigger → wait → collect & classify → fix**.

**Isolation**: Each stream runs in its own **git worktree** (pre-created by the lead — the `isolation` flag is unreliable; see the quirk section above). This lets streams edit and commit independently without conflicting. Step 3 (Merge) cherry-picks commits from each worktree back into the main branch.

Before fixing any finding, a stream must **claim** it via task ownership (see Inter-Stream Communication below). If another stream already owns a task at the same location, skip it.

#### CI Stream

1. **Trigger**: CI runs automatically on push. Nothing to do.
2. **Wait**: Watch runs using the Watch and Collect procedure (see below).
3. **Collect & Classify**: For each failed run, diagnose from logs. Record as findings with severity, location, description. Verify each finding exists in current code.
4. **Fix**: For each valid finding — create a task via `TaskCreate`, claim ownership via `TaskUpdate`. If another stream already owns a task at that location, skip. Apply fix, commit, mark task `completed`.

#### Grumpy Stream

1. **Trigger**: Invoke `/grumpy-review` locally (runs inline and spawns its own reviewer agents; produces severity-ranked JSON report).
2. **Wait**: Grumpy-review runs locally and completes.
3. **Collect & Classify**: Read the grumpy-review JSON report. Each finding already has severity. Verify findings exist in current code, discard outdated/false positives. Filter to MEDIUM+.
4. **Fix**: For each valid MEDIUM+ finding — create a task and claim ownership per Inter-Stream Communication. If already owned, skip. Apply fix, commit, mark task `completed`.

#### Review Stream

1. **Trigger**: Request copilot review: `gh pr edit --add-reviewer @copilot || true`
2. **Wait**: Poll for new reviews using `${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh`. Compare review IDs to detect new ones.
   - Poll interval: 30 seconds
   - Minimum wait: 5 minutes
   - Maximum wait: 20 minutes — proceed without if no review appears
   - Also check for any OTHER reviews (human or bot) that may have been added since last iteration
3. **Collect & Classify**: Fetch all review comments via `/check-pr-comments` (skip confirmations). Classify each: verify issue exists in current code, rate severity, check for false positives. Filter to MEDIUM+.
4. **Fix**: For each valid MEDIUM+ finding — create a task and claim ownership per Inter-Stream Communication. If already owned, skip. Apply fix, commit, mark task `completed`.

### Inter-Stream Communication

Streams coordinate via the Teams infrastructure to prevent duplicate fixes.

**Finding Discovery**: When a stream finds something worth fixing, create a task:
```
TaskCreate(subject="Fix: unused import in src/main.rs:42", description="CI failure: ...", metadata={stream: "ci", file: "src/main.rs", line: 42, severity: 3})
```

**Claiming**: Before fixing, check `TaskList` for existing tasks at the same file/line range. If none, create the task and set `owner` to self via `TaskUpdate`. If another stream already owns a task at that location, skip it. `TaskUpdate` ownership is atomic — no race conditions.

**Completion**: After fixing, mark the task `completed` via `TaskUpdate(status="completed")`.

**Direct Coordination**: Use `SendMessage` for real-time alerts between streams:
```
SendMessage(to="grumpy-stream", message="I'm fixing src/auth.rs:17-25, skip this area")
```
Use for: overlapping finding alerts, completion summaries, conflict flags.

### Step 3: Merge

After all three streams complete:

1. `TaskList` — review all tasks, their status and outcomes
2. Enumerate worktree branches — collect commits from each stream's worktree
3. Cherry-pick each stream's commits into the main working branch
4. If cherry-pick conflicts (two streams edited overlapping lines despite task coordination), resolve — prefer the more comprehensive fix
5. Clean up team with `TeamDelete`
6. Clean up worktrees (`git worktree remove` + `prune`)
7. The merged working tree is ready for the next push

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
- **Findings**: total found, fixed, skipped (with severity breakdown)
- **Unresolved**: any remaining issues (with severity)
- **PR URL**: for easy access

## Notes

- Do not duplicate sub-skill logic — delegate to `/push`, `/grumpy-review`, `/check-pr-comments`
- When sub-skills have confirmation steps, skip them — this skill's invocation is the blanket confirmation
- Give GitHub ~5 seconds after push before listing new workflow runs
- Clean up team with `TeamDelete` after merging stream results
- **Not for GitHub Actions** — this skill pushes commits that trigger CI, so running it inside a workflow causes concurrency cancellation loops. Use from CLI only.
