# Codex Sandbox, Job State & Recovery — Reference

Deep mechanics behind `codex-crew`. Load when a Codex job misbehaves (write rejected, commit blocked, dispatch fails instantly) or when hand-monitoring a job.

## Sandbox Modes

Codex CLI supports three sandbox modes:

| Mode | Behavior |
|---|---|
| `read-only` (default / review) | No writes; review/diagnosis runs. |
| `workspace-write` | Writes under cwd + configured `writable_roots`; network disabled unless `network_access = true`. Used for any `--write` `task` dispatch. |
| `danger-full-access` | No sandbox. Not used by claudius dispatch. |

## `workspace-write` Config (this host)

`~/.codex/config.toml`:

```toml
sandbox_mode = "workspace-write"
model = "gpt-5.6-sol"
model_reasoning_effort = "high"

[sandbox_workspace_write]
# Self-commit scope (repo .git) intentionally NOT added yet
writable_roots = ["/data/git-worktrees", "/data/tmp", "/data/artifacts", "/data/target"]
network_access = true
```

- The first `writable_roots` entry should track `$CLAUDIUS_WORKTREE_ROOT` when the configured worktree root changes.
- `writable_roots` **adds** to the always-writable workspace root (cwd): `/data` worktrees, scratch, and the shared cargo target dir (`/data/target`).
- Do not treat the `/data/artifacts` config entry as an effective write guarantee. A dispatched job has observed a narrower or stale ACL and failed there as read-only while otherwise completing normally. Have Codex return report or artifact content through `result.rawOutput`; the coordinator then writes it under `/data/artifacts`.
- `network_access = true` unblocks localhost test sockets — and also enables general outbound network, the tradeoff `workspace-write` disables by default.
- The `# Self-commit scope ... NOT added yet` comment is misleading as an explanation of commit behavior (see below) — kept verbatim as live config text, but not proof commit is blocked.
- Validate any change with `codex --strict-config doctor` (hard-errors on unknown fields). Keep a timestamped backup of `config.toml` before editing.

## Git Commit in a Linked Worktree — Status

**Confirmed inconsistent — both outcomes observed the same day, same repo.** Dispatch 1: Codex ran `git add` + `git commit` in a linked worktree successfully (commit `f2639aa`, verified via `git log`/`git show`, no approval prompt). Dispatch 2, a different worktree later that day: `git add` failed with `fatal: Unable to create '.../index.lock': Read-only file system` — the exact historical error below — and the coordinator committed instead (`7c2d3e8`).

`writable_roots` was unchanged across both and still excludes the repo `.git`, so it is not the lever, and the gate isn't a static per-repo setting. Working theory: `approval_policy = "on-request"` plus the project's `trust_level = "trusted"` entry (`[projects."<repo>"] trust_level = "trusted"`) sometimes auto-approves the escalated git-metadata write — not independently confirmed. **A successful Codex commit is NOT evidence the fallback is no longer needed** — the very next dispatch can hit the old block.

**Pattern:** instruct Codex to run its own `git add`/`git commit` as the final dispatch step (with an explicit, well-formed commit message — it doesn't know the project's conventions unless given them), then verify independently (`git -C <worktree> log`/`git status`) rather than trusting Codex's self-report, and commit yourself when it didn't land. Pushing remains the coordinator's job regardless of who committed, and still requires explicit user authorization.

**When commit fails:** symptom is a job `errorMessage` like *"the sandbox prevented creating the requested commit because the worktree's Git metadata is read-only"*, or a git error about `index.lock` under the main repo's external `.git`. Routine and expected, not a regression — the coordinator commits: Codex writes files only; the coordinator (unsandboxed) runs `git -C <worktree> add -A && git -C <worktree> commit -m ...`.

### Historical mechanics (why it was blocked before — for troubleshooting the fallback case)

Two stacked restrictions were previously confirmed:

1. **Path allowlist.** A linked worktree created by `git worktree add <worktree-root>/foo` from main repo `/home/ubuntu/git/<repo>` stores its git metadata (HEAD, index, refs) under the **main repo's** `.git/worktrees/foo/`, and objects under the main repo's `.git/objects/` — outside the sandbox's writable set, so `git commit` (which writes `index.lock`, refs, objects there) is rejected under a strict path allowlist alone.
2. **Git-metadata block.** A separate read-only block on git metadata was observed even when the path was writable — widening `writable_roots` to include the repo `.git` was not considered a reliable fix.

If the fallback triggers, investigate these mechanics first.

## On-Disk Job State (for Monitoring)

Codex job state lives under `$CLAUDE_PLUGIN_DATA/state/` (default `CLAUDE_PLUGIN_DATA=/home/ubuntu/.claude/plugins/data/codex-openai-codex`), one directory per workspace:

```
state/<workspace-slug>-<hash>/
  broker.json            # broker endpoint + cwd (workspaceRoot)
  state.json             # {version, config, jobs:[...]}  — embeds ALL jobs; grows unbounded
  jobs/<job-id>.json     # per-job record (small)
  jobs/<job-id>.log      # streamed progress + final result / error text
```

Per-job `.json` fields worth reading: `id`, `status` (`pending` | `running` | `completed` | `failed`), `phase`, `errorMessage`, `startedAt`, `completedAt`, `workspaceRoot`, `logFile`, `pid`, `result`. `pid` is `null` for some job classes (running inside the shared app-server), but `task-worker`-class jobs (spawned as `codex-companion.mjs task-worker --cwd <dir> --job-id <id>`) carry a real pid — cross-check with `ps -p <pid>` or `/proc/<pid>`; a populated `pid` with no matching process means the Codex engine crashed silently while `status` stays stuck at `"running"` forever (the record is never updated on crash). `result.rawOutput` is the full final report text — read it directly; `result.touchedFiles` lists what the job actually edited.

**One-shot lookup by job id**: `scripts/minion-monitoring.py --dump-job <job-id>` searches every known workspace's `jobs/<job-id>.json` (no team/session/worktree setup) and prints the full record — including `result.rawOutput`/`result.touchedFiles` — then exits. Prefer it over a hand-rolled `python3 -c "..."` read; it's tested and handles not-found and malformed records cleanly (exit 1, clear stderr, no traceback).

**Memory discipline (long sessions).** Do **not** parse `state.json` per poll — it embeds every job and grows over the session. Instead:

- Use the newest mtime under `jobs/` (or `state.json`'s mtime) as the cheap **activity clock**.
- Parse an individual `jobs/<id>.json` only when its mtime advanced since the last poll; extract only the few fields above.
- Keep a bounded per-job last-seen map (`job-id → {status, mtime}`), never accumulated JSON.

For a direct dispatch, `workspaceRoot` is exactly the `--cwd` passed to `task` — map a monitored worktree to its state dir by that path. (Only the interactive `codex:codex-rescue` path, which never passes `--cwd`, has `workspaceRoot` reflect the *dispatching session's* cwd instead — if several such dispatches share one session cwd, match each to its request by `startedAt` proximity and `result.touchedFiles`, never by `sessionId`, which each carries independently and unpredictably.) `status: failed` with an `errorMessage` is the signal to surface — exactly the class (e.g. the read-only-`.git`/`index.lock` self-commit failure above) that otherwise goes unnoticed.

`codex exec --json` also emits a JSONL event stream (`thread.started`, `turn.completed`, `item.completed`, `error`) for foreground runs — an alternative progress signal outside the companion's job state.

## Harness Kills of a Backgrounded Task

A `codex-companion.mjs task --write --background` run launched via a `run_in_background` Bash call can be killed by the harness mid-run — confirmed via a tmux pane reading `Background command ... was stopped`. Nothing reports it automatically: `--background` detaches and returns immediately, so nobody is polling the task once queued. **Silence is not evidence of health.**

- **Detect it coordinator-side.** Periodically read the job's log (`jobs/<job-id>.log`) and inspect the tmux pane. Don't infer health from `status` alone — it can sit at `running` after the process is gone.
- **On-disk edits survive.** Files Codex already wrote stay written; the work is partial, not lost.
- **Cancel before resuming.** A harness-killed job can retain a broker/job-registry lock after its OS process dies, so a direct same-cwd `--resume-last` fails with `Task task-<id> is still running`. From the job's own `--cwd`, run `node "$CODEX_ROOT/scripts/codex-companion.mjs" cancel <job-id> --json`, then confirm `status --all` no longer lists it as running.
- **Resume, don't restart.** Only after cancellation, redispatch with `--resume-last` and the identical `--cwd` to continue from the surviving state.

`cancel` appears cwd-scoped: observed calls from another cwd returned `No active job found for "<job-id>".`, while calls from the job's own `--cwd` succeeded. Treat this scope as observed but unconfirmed.

## Broker Recovery

Each worktree dispatch runs its own broker: `app-server-broker.mjs serve --endpoint unix:/tmp/cxc-<id>/broker.sock --cwd <worktree>`. Removing and recreating a worktree at the same path while its broker still runs strands the broker; the next dispatch fails in ~0 s with a misleading `failed to resolve feature override precedence` / `auth.loggedIn: false` error.

Recovery:

```bash
# 1. Find the orphaned broker (its --cwd points at the old/recreated worktree path)
ps aux | grep 'app-server-broker.mjs' | grep '<worktree-path>'
# 2. Kill it and remove its socket dir
kill <pid>
rm -rf /tmp/cxc-<id>
# 3. Redispatch — a fresh broker binds automatically
```

Avoid worktree remove+recreate at an identical path during an active session; when unavoidable, recover the broker first.
