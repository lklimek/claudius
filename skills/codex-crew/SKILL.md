---
name: codex-crew
description: Use before dispatching work to Codex Sol — deciding whether to route coding to Codex, dispatching directly via codex-companion.mjs (not the codex:codex-rescue subagent), handling a Codex job that fails to write or commit, monitoring a running Codex job, or recovering a stale Codex broker. Pre-flight the coordinator reads once before its first Codex dispatch of a session.
---

# Codex Crew — Enlisting Codex Agents

Codex agents (OpenAI Codex CLI, run via the `codex` plugin's `codex-companion.mjs` runtime) are external crew a coordinator can enlist alongside the claudius roster. Opt-in. Read once before the session's first Codex dispatch.

**Dispatch directly, never through `codex:codex-rescue`.** For coordinator-orchestrated work that subagent is pure overhead: one `Bash` call forwarding stdout unchanged — no monitoring, no analysis, unreliable lifecycle signals (`idle_notification`, teammate shutdown, stall tracking) layered over a worker that is already a detached Node process with its own job-state files — and it never exposes `--cwd`/`--prompt-file`, the root cause of most bugs below. Call `codex-companion.mjs task` directly (§ Direct Dispatch): nothing to spawn, track, or shut down. Reserve `codex:codex-rescue` for the user-typed `/codex:rescue` interactive command, which this skill doesn't govern.

## When to Enlist Codex

- **Opt-in, not default** — when the user asks, or per the coding preference below.
- **Coding-first (project default):** code-writing work prefers **Codex Sol** over Opus-tier claudius agents (`developer-bilby`) — an intentional override of `delegate`'s Token Economy tiering for implementation tasks.
- **Non-coding roles keep normal tiering:** review, QA, security, architecture, and docs stay with claudius agents unless the user opts them into Codex.

## Routing — One Model, High Effort

- **Codex Sol = `--model gpt-5.6-sol --effort high`. Always high effort.** State both flags on every dispatch — omitting either drops to the runtime default, not Sol.
- Dispatch via `codex-companion.mjs task` directly (§ Direct Dispatch). Nothing monitors, polls, or fetches results on its own — that's coordinator work (§ Monitoring). Codex CAN attempt a commit when the prompt instructs it, but success is inconsistent; verify independently (Sandbox & Workdir rule 2).
- The lighter `spark` alias (`gpt-5.3-codex-spark`) exists; claudius standardizes on Sol at high effort.

## Direct Dispatch

Resolve the installed `codex` plugin's script root once per session — version-pinned cache dirs shift on plugin updates, never hardcode a version:

```bash
CODEX_ROOT=$(find ~/.claude/plugins/cache/openai-codex/codex -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)
```

Write the prompt to a file — never inline it as a shell argument (long prompts with nested quotes or Rust `Debug` dumps corrupt under shell quoting). `task` accepts `--prompt-file <path>` (also reads piped stdin); a relative path resolves against `--cwd`, so always pass an **absolute** path (e.g. under `/data/tmp`).

```bash
node "$CODEX_ROOT/scripts/codex-companion.mjs" task \
  --cwd <worktree-abs-path> \
  --prompt-file /data/tmp/<descriptive-name>.txt \
  --write --background \
  --model gpt-5.6-sol --effort high
```

- **`--cwd <worktree-abs-path>` binds the broker/workspace slug to the intended worktree** — pass it on every dispatch; never rely on the invoking shell's cwd or on prompt text telling Codex to `cd` (prompt text has zero effect on cwd resolution — rule 3).
- **`--write` is not implied** — without it the run is silently read-only (reports normal completion, touches zero files).
- **`--background`** returns a job id almost instantly; the coordinator polls job state (§ Monitoring a Codex Job) rather than blocking.
- **Continuing a thread:** `--resume-last` (= `--resume`) with the **identical** `--cwd` — threads are found by workspace, so a mismatched `--cwd` resumes nothing.

## Plan-Approval Gate

**Sandbox write mode is pinned when the Codex app-server creates a thread; a resume cannot escalate it.** Reproduced twice: a thread first dispatched without `--write` stayed read-only under `--resume-last --write`, `apply_patch` rejected. Never plan without `--write` then resume with it.

For a well-scoped task that might write anything, dispatch the first turn with `--write`. For a genuine approval gate on large or risky work:

1. Dispatch a read-only investigation and plan without `--write`.
2. After approval, start a **fresh job** (never `--resume-last`) with `--write`, embedding the approved plan plus any revisions in its prompt.

The fresh job rebuilds context, but is the only safe read-only-to-writable boundary. `grand-admiral` § Development-Work Delegation remains the source of truth for the coordinator's plan review.

## Sandbox & Workdir — The Load-Bearing Rules

Codex runs under `sandbox_mode = "workspace-write"` (see `~/.codex/config.toml`). Three rules:

1. **Write scope = cwd + configured `writable_roots`.** On this host: the worktree root (`$CLAUDIUS_WORKTREE_ROOT`; see `grand-admiral` § Worktree Isolation), `/data/tmp`, `/data/artifacts`, `/data/target` (shared cargo target dir), plus `network_access = true`. So worktrees, scratch, and cargo build output are writable, and sandboxed tests can bind localhost sockets. Paths outside cwd and `writable_roots` are read-only. `scripts/cargo-cached.sh` handles its verification ledger itself: when the default `~/.cache/claudius/ledger` root is unreachable in-sandbox it falls back to a workspace-local dir (the script is the source of truth).

2. **Codex `git commit` in a linked worktree is inconsistent — confirmed both ways, same repo, same day.** One dispatch committed cleanly, no approval prompt; a later one hit the "Git metadata is read-only"/`index.lock` error and the coordinator committed instead. `writable_roots` was unchanged across both, so the gate isn't a static config value (suspected `approval_policy = "on-request"` + `trust_level = "trusted"` interaction — unconfirmed). **Coordinator-commit is the reliable default, not a fallback:** fine to instruct Codex to attempt `git add`/`git commit` as its final step (with an explicit commit message — it doesn't know your conventions), but plan for failure: verify via `git log`/`git status` in the worktree — never trust Codex's self-report — and commit yourself (unsandboxed) when it didn't land. See `references/sandbox-and-recovery.md` § Git Commit in a Linked Worktree.

3. **All worktrees live at `<worktree-root>/<slug>`** (`$CLAUDIUS_WORKTREE_ROOT`, default `/data/git-worktrees`; slug derived from the startup `$PWD`), pre-created by the coordinator per `grand-admiral` § Worktree Isolation. **The broker keys off `codex-companion.mjs`'s own resolved cwd, not any path in prompt text** — confirmed: a dispatch told via prompt to `cd` into a pre-created worktree still bound its broker to the coordinator's plain checkout, blocking ALL writes (even under `writable_roots`, even on the FIRST dispatch). Pass the worktree via `--cwd` instead (§ Direct Dispatch). Each dispatch's `--cwd` is self-contained, so N worktrees can be dispatched genuinely concurrently — no `EnterWorktree`/`ExitWorktree` serialization.

Deep mechanics (exact sandbox modes, on-disk job-state layout, worktree-commit status and fallback) are in `references/sandbox-and-recovery.md`.

### Never Dispatch Concurrently to the Same `--cwd`

**Never fire dispatch N+1 at the same `--cwd` until dispatch N's job JSON shows a terminal `status`** (`completed`/`failed`). The broker/workspace slug is keyed off `--cwd`, so distinct worktree paths don't collide; the risk is two dispatches at the *same* `--cwd` (a read-only plan job then a fresh writable job, or a retry). Confirmed: same-cwd dispatches minutes apart still collided — elapsed time and a prior dispatch already having its own job-state file are NOT protective; only polling for terminal status is. A collision either strands the earlier dispatch at `status=running` forever with no completion signal (silent orphan), or instantly returns Codex's generic capabilities boilerplate with `touchedFiles: []` (looks like a trivial done, isn't). Root cause — one broker per workspace slug, not per job — lives in the `openai-codex` plugin and cannot be fixed from this repo.

Mitigation: poll for terminal status before the next same-cwd dispatch (never a fixed stagger delay). `scripts/minion-monitoring.py` should eventually catch a stuck orphan as `CODEX_STALL reason=no-progress` — a detection backstop, not a substitute. After any dispatch, sanity-check the job's `workspaceRoot` matches the intended worktree and its `rawOutput` actually engages the dispatched task — a suspiciously fast, generic-sounding completion is a collision red flag, not evidence the task was trivial.

## Monitoring a Codex Job

**MCP watchdog covers Codex too** (`runtime: codex_cli`/`codex_companion` in `register_session`) — prefer it over the `CODEX_*` machinery below when available (see `grand-admiral` § Recovery → MCP Watchdog), with the same corroborate-before-acting caution.

**Direct dispatch has no agent lifecycle to watch — by design.** A `--background` dispatch is a detached Node process with on-disk job-state files: no subagent, no `idle_notification`, nothing to shut down. Go straight to the job-state file. (If `codex:codex-rescue` is ever in play — the interactive `/codex:rescue` command — treat its `idle_notification` as worthless in either direction: confirmed 4-for-4 in one wave, jobs sat `completed` 40–85 minutes before the wrapper reported.)

**Primary method: read the job's on-disk state directly** (mtime-gated, minimal-field reads — never the full state blob). See `references/sandbox-and-recovery.md` § On-Disk Job State for the field list, `result.rawOutput`/`result.touchedFiles` usage, and matching jobs to dispatches. Load-bearing, not a fallback — it is what actually recovers status/results when the stall watchdog can't.

**Get notified, don't just poll on request.** Arm a `Bash` `run_in_background` until-loop on the job's own `state/<workspace-slug>-<hash>/jobs/<job-id>.json` (resolve the path per § On-Disk Job State) — a single, job-specific completion signal needing no team/session discovery:

```bash
until python3 -c "
import json
try:
    d = json.load(open('state/<workspace-slug>-<hash>/jobs/<job-id>.json'))
except Exception:
    exit(1)
exit(0 if d.get('status') in ('completed','failed','cancelled','canceled') else 1)
"; do sleep 20; done
```

The loop is itself a backgrounded Bash call and inherits the silent-kill risk of § Harness Kills of a Backgrounded Task — periodically confirm it's alive; silence is not health.

`ScheduleWakeup` is not a substitute — it's `/loop` dynamic-mode-only and errors outside that context.

- The built-in stall watchdog (`grand-admiral` § Recovery → Built-in Stall Watchdog, `scripts/minion-monitoring.py`) discovers Codex jobs and emits `CODEX_*` transition events when the MCP watchdog isn't in use. A watchdog — MCP or built-in — is **mandatory** whenever any agent, Claude or Codex, is dispatched (see `grand-admiral` § Spawning → Monitoring). Treat `CODEX_*` events as **best-effort, layered on top of** the direct job-state check — never a substitute.
- **Codex discovery requires `--worktrees`** — a direct dispatch is never a teammate, so `--worktrees` pointed at the configured worktree root is the only way the built-in watchdog sees it. Without it: a one-time startup warning, then silently zero Codex monitoring.
- **Direct discovery (`--worktrees`/Source C) bypasses the session gate entirely** — a workspace under the worktree root surfaces every job's `CODEX_*` events regardless of `sessionId`. The strict single-session match applies only to *ambient* discovery (a workspace reachable solely via team lead/member cwd, not also under the worktree root) — `codex-companion.mjs` stamps each job's `sessionId` from its own dispatching session, never the coordinator's, so the ambient path can under-report on a mismatch. The direct job-state check is unaffected either way — which is why it's primary.
- Don't guess the Monitor's `--session-id`: derive `--team-dir` from a spawn's own `agent_id` per `grand-admiral`'s `references/stall-watchdog.md` (linked from § Recovery → Built-in Stall Watchdog).

## Recovering a Stale Broker

Each worktree dispatch spins up its own broker (`app-server-broker.mjs` bound to `/tmp/cxc-<id>/broker.sock`, `--cwd` = the worktree). Removing and recreating a worktree at the **same path** while its broker still runs strands it: the next `task` dispatch against that path fails instantly (~0 s) with a misleading auth-shaped error (`failed to resolve feature override precedence` / `auth.loggedIn: false`).

Recovery: find the orphaned broker PID (its `--cwd` points at the old worktree path), `kill` it, `rm -rf /tmp/cxc-<id>`, then redispatch — a fresh broker binds automatically. Exact commands: `references/sandbox-and-recovery.md` § Broker Recovery.

## Additional Resources

- **`references/sandbox-and-recovery.md`** — sandbox modes, `workspace-write` config, on-disk job-state layout for monitoring, git-commit-in-a-worktree status (inconsistent) and its fallback, harness kills of a backgrounded task and how to resume, and copy-paste broker-recovery commands.
