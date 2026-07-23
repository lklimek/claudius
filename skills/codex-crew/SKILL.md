---
name: codex-crew
description: Use before dispatching work to Codex Sol — deciding whether to route coding to Codex, dispatching directly via codex-companion.mjs (not the codex:codex-rescue subagent), handling a Codex job that fails to write or commit, monitoring a running Codex job, or recovering a stale Codex broker. Pre-flight the coordinator reads once before its first Codex dispatch of a session.
---

# Codex Crew — Enlisting Codex Agents

Codex agents (OpenAI Codex CLI, run via the `codex-companion.mjs` runtime bundled with the `codex` plugin) are external crew a coordinator can enlist alongside the named claudius roster. Use of Codex is **opt-in**. Read this once before the first Codex dispatch of a session — it covers routing, direct dispatch, the sandbox's hard limits, how to monitor a Codex job, and how to recover a stuck broker.

**Dispatch directly, not through `codex:codex-rescue`.** For coordinator-orchestrated work, `codex:codex-rescue` is pure overhead: a Claude subagent whose entire contract is one `Bash` call to `codex-companion.mjs task`, forwarding stdout unchanged — it never monitors, never adds analysis, and its own lifecycle (`idle_notification`, teammate shutdown, stall-watchdog tracking) is a second, *unreliable* signal layered on top of the actual worker, which is already a detached Node process with its own job-state files. Worse, its forwarding contract never exposes `--cwd`/`--prompt-file`, which is the root cause of most of the bugs documented below. Call `codex-companion.mjs task` directly instead (§ Direct Dispatch) — no agent to spawn, track, or shut down. Reserve `codex:codex-rescue` for the upstream, user-typed `/codex:rescue` interactive command, which this skill doesn't govern.

The recurring failure this skill prevents: coordinators re-derive the same Codex sandbox and orchestration quirks session after session, each losing time to the same write-rejection and broker-staleness traps (and an inconsistent commit path — see Sandbox & Workdir rule 2).

## When to Enlist Codex

- **Opt-in, not the default.** Reach for Codex when the user asks for it, or per the standing coding preference below.
- **Coding-first (project default).** Actual code-writing work prefers **Codex Sol** over Opus-tier claudius agents (`developer-bilby`). This intentionally overrides `delegate`'s Token Economy model tiering for implementation tasks.
- **Non-coding roles keep normal tiering.** Review, QA, security, architecture, and docs stay with their claudius agents unless the user explicitly opts them into Codex.

## Routing — One Model, High Effort

- **Codex Sol = `--model gpt-5.6-sol --effort high`. Always high effort.** State both flags explicitly on every direct dispatch — omitting either drops to the runtime default, not Sol.
- **Dispatch via `codex-companion.mjs task` directly** (§ Direct Dispatch below), not via the `codex:codex-rescue` subagent. Nothing monitors, polls, or fetches results on its own — that's **coordinator** work (see Monitoring below). Codex CAN attempt a commit when the dispatch prompt explicitly instructs it to, but success is inconsistent; the coordinator must verify independently (see Sandbox & Workdir rule 2).
- The lighter `spark` alias (`gpt-5.3-codex-spark`) exists, but claudius routing standardizes on Sol at high effort.

## Direct Dispatch

Resolve the installed `codex` plugin's script root once per session — version-pinned cache dirs shift on plugin updates, so never hardcode a version:

```bash
CODEX_ROOT=$(find ~/.claude/plugins/cache/openai-codex/codex -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)
```

Write the prompt to a file first — never inline it as a shell argument. `task` accepts `--prompt-file <path>` (also reads piped stdin), and a relative `--prompt-file` path resolves against `--cwd`, so always pass an **absolute** path (e.g. under `/data/tmp`). This sidesteps the quote/escaping corruption a long inline prompt (nested quotes, Rust `Debug` dumps, etc.) suffers when built as a shell argument.

```bash
node "$CODEX_ROOT/scripts/codex-companion.mjs" task \
  --cwd <worktree-abs-path> \
  --prompt-file /data/tmp/<descriptive-name>.txt \
  --write --background \
  --model gpt-5.6-sol --effort high
```

- **`--cwd <worktree-abs-path>` binds the broker/workspace slug to the intended worktree explicitly** — no `EnterWorktree` dance needed just to make Codex write to the right place. Pass it on every dispatch; never rely on the invoking shell's own cwd or on prompt text telling Codex to `cd` (prompt text has zero effect on `codex-companion.mjs`'s own cwd resolution — see Sandbox & Workdir rule 3).
- **`--write` is not implied** — omit it and the run is silently read-only (reports normal completion, touches zero files).
- **`--background`** returns almost instantly with a job id once the detached worker is queued; the coordinator polls job state (§ Monitoring a Codex Job) rather than blocking.
- **Continuing a thread**: `--resume-last` (equivalent to `--resume`) on a second dispatch with the **identical** `--cwd` — the thread is found by workspace, so a mismatched `--cwd` resumes nothing.

## Plan-Approval Gate

**Sandbox write mode is pinned when the Codex app-server creates a thread; a resume cannot escalate it.** Independently reproduced twice: a thread whose first turn omitted `--write` stayed read-only under `--resume-last --write`, and `apply_patch` was rejected before any file changed. Never use the old plan-without-`--write`, then resume-with-`--write` sequence.

For a well-scoped task that might write anything, dispatch the first turn with `--write`. For large or risky work that needs a genuine approval gate:

1. Dispatch a read-only investigation and plan without `--write`.
2. After approval, start a **fresh job** (never `--resume-last`) with `--write` and embed the approved plan plus any revisions in its prompt.

The fresh job rebuilds context, but it is the only safe read-only-to-writable boundary. `grand-admiral` § Development-Work Delegation remains the source of truth for the coordinator's plan review.

## Sandbox & Workdir — The Load-Bearing Rules

Codex runs under `sandbox_mode = "workspace-write"` (see `~/.codex/config.toml`). Three rules carry all the weight:

1. **Write scope = cwd + configured `writable_roots`.** On this host `writable_roots` includes the worktree root (`$CLAUDIUS_WORKTREE_ROOT`; see `grand-admiral` § Worktree Isolation), `/data/tmp`, `/data/artifacts`, `/data/target` (the shared cargo target dir), plus `network_access = true`. So worktrees under `$CLAUDIUS_WORKTREE_ROOT/<slug>` **are** writable by Codex, scratch under `/data/tmp` and `/data/artifacts` is writable, cargo build output under `/data/target` is writable, and sandboxed tests **can** bind localhost sockets. Paths outside cwd and `writable_roots` are read-only. `scripts/cargo-cached.sh`'s verification ledger handles this on its own: when the default `~/.cache/claudius/ledger` root is unreachable from inside the sandbox, it falls back to a workspace-local directory rather than hard-failing (the script remains the source of truth for the mechanism).

2. **Codex `git commit` in a linked worktree is inconsistent — confirmed both ways the same day (2026-07-16).** One dispatch committed cleanly (`f2639aa`, this repo, no approval prompt). A later dispatch, same repo, different worktree, hit the exact old "Git metadata is read-only"/`index.lock` error and had to be committed by the coordinator instead (`7c2d3e8`). `writable_roots` was unchanged across both, so whatever gates this isn't a static config value — likely `approval_policy = "on-request"` + `trust_level = "trusted"` interacting with something per-dispatch, not independently confirmed. **Treat coordinator-commit as the reliable default, not a fallback**: it is fine to instruct Codex to attempt `git add`/`git commit` itself as its final step (with an explicit commit message — it doesn't know your conventions unless told), but always plan for that attempt to fail and verify afterward — check `git log`/`git status` in the worktree rather than trusting Codex's self-report, and commit yourself (unsandboxed) when it didn't land. See `references/sandbox-and-recovery.md` § Git Commit in a Linked Worktree for both data points.

3. **All worktrees live under the configured root** (`$CLAUDIUS_WORKTREE_ROOT`, default `/data/git-worktrees`) at `<worktree-root>/<slug>`, where the slug derives from the startup `$PWD`. The coordinator pre-creates the worktree following the isolation pattern in `grand-admiral` § Worktree Isolation. **The broker keys off `codex-companion.mjs`'s own resolved cwd, not any path mentioned in prompt text** — confirmed 2026-07-21: a dispatch instructed via prompt text to `cd` into a pre-created worktree still bound its broker to the coordinator's plain checkout, blocking ALL writes (including under `writable_roots`) even on the FIRST dispatch. Pass the worktree path via the direct dispatch's `--cwd <worktree-abs-path>` flag instead (§ Direct Dispatch) — this also means concurrent dispatches to different worktrees no longer require serializing the coordinator's own cwd through `EnterWorktree`/`ExitWorktree`; each dispatch's `--cwd` is self-contained, so N worktrees can be dispatched to genuinely concurrently.

Deep mechanics (exact sandbox modes, the on-disk job-state layout, `git commit` in a linked worktree status and fallback) are in `references/sandbox-and-recovery.md`.

### Never Dispatch Concurrently to the Same `--cwd`

**Never fire dispatch N+1 with the same `--cwd` as dispatch N until N reaches a terminal job status.** The broker/workspace slug is keyed off `--cwd` — pass distinct worktree paths and distinct dispatches no longer collide (this replaces the old requirement to serialize through `EnterWorktree`/`ExitWorktree`, see Sandbox & Workdir rule 3). The remaining risk is real only when two dispatches genuinely target the *same* `--cwd` (a read-only plan job followed by a fresh writable job at the same `--cwd`, or a retry) before the first reaches `completed`/`failed`. Confirmed: even same-cwd dispatches minutes apart still collided — elapsed time and a prior dispatch already having its own job-state file were NOT protective — the only safe rule is polling that dispatch N's job JSON shows a terminal `status` before firing N+1 at that same `--cwd`. A collision either strands the earlier dispatch at `status=running` forever with no completion signal (silent orphan), or — observed separately — the earlier dispatch instantly returns Codex's generic capabilities boilerplate with `touchedFiles: []` as if it never received the real prompt (looks like a trivial done, isn't). The root cause (one broker per workspace slug, not per job) lives in the separate `openai-codex` plugin and cannot be fixed from this repo.

Mitigation: poll for terminal job status before the next dispatch at a given `--cwd` (never a fixed stagger delay). `scripts/minion-monitoring.py` should eventually catch a stuck orphan as `CODEX_STALL reason=no-progress` — a detection backstop, not a substitute for avoiding the collision. After any dispatch, sanity-check the job's `workspaceRoot` matches the intended worktree and its `rawOutput` actually engages the dispatched task — a suspiciously fast, generic-sounding completion is a collision red flag, not evidence the task was trivial.

## Monitoring a Codex Job

**MCP watchdog covers Codex too** (`runtime: codex_cli`/`codex_companion` in `register_session`) — prefer it over the `CODEX_*` machinery below when available (see `grand-admiral` § Recovery → MCP Watchdog), with the same corroborate-before-acting caution.

**Direct dispatch has no agent lifecycle to watch — by design.** A `--background` dispatch is a detached Node process with on-disk job-state files; there's no subagent to send `idle_notification`, no teammate to stall-watch, nothing to shut down. Go straight to the job-state file. (If `codex:codex-rescue` is ever used — the upstream interactive `/codex:rescue` command — treat its `idle_notification` as worthless in either direction: confirmed 4-for-4 in one wave, jobs sitting `completed` 40–85 minutes before the wrapper ever reported.)

**Primary method: read the job's on-disk state directly** (mtime-gated, minimal-field reads — never load the full state blob). See `references/sandbox-and-recovery.md` § On-Disk Job State for the field list, `result.rawOutput`/`result.touchedFiles` usage, and matching jobs to dispatches. This is load-bearing, not a fallback — it is what actually recovers status/results when the stall watchdog can't.

**Get notified, don't just poll on request.** Arm a `Bash` `run_in_background` until-loop on that job's own `state/<workspace-slug>-<hash>/jobs/<job-id>.json` (resolve the path per § On-Disk Job State above) — a single, job-specific completion signal that needs no team/session discovery:

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

This loop is itself a backgrounded Bash call, so it inherits the same silent-kill risk as § Harness Kills of a Backgrounded Task below — periodically confirm it's still alive rather than trusting silence as health.

`ScheduleWakeup` is not a substitute — it's `/loop` dynamic-mode-only and errors outside that context. Don't reach for it as an ad-hoc "check back later" for a Codex dispatch.

- The built-in stall watchdog (`grand-admiral` § Recovery → Built-in Stall Watchdog, `scripts/minion-monitoring.py`) discovers Codex jobs and emits `CODEX_*` transition events when the MCP watchdog isn't in use. A watchdog — MCP or built-in — is **mandatory** whenever any agent — Claude or Codex — is dispatched (see `grand-admiral` § Spawning → Monitoring). Treat its `CODEX_*` events as **best-effort, layered on top of** the direct job-state check above — never as a substitute for it.
- **Codex discovery requires `--worktrees` — direct dispatch has no team-membership path at all.** The watchdog reaches Codex jobs only through named teammates or an explicit `--worktrees` path on the Monitor command; a direct `codex-companion.mjs` dispatch is never a teammate, so `--worktrees` pointed at the configured worktree root is the *only* way the built-in watchdog sees it. Without it, the watchdog emits a one-time startup warning and Codex monitoring is silently zero.
- **Direct discovery (`--worktrees`/Source C) now bypasses the session gate entirely** — a workspace found under the worktree root surfaces every job's `CODEX_*` events regardless of `sessionId`, closing the multi-teammate blind spot as long as the Monitor's `--worktrees` points at the configured root (see bullet above). The strict single-session match still applies to *ambient* discovery only (a workspace reachable solely via team lead/member cwd, not also under the worktree root) — `codex-companion.mjs` stamps each job's `sessionId` from its own dispatching session, never the coordinator's, so that narrower path can still under-report a mismatched session. The direct job-state check above is unaffected by any of this either way, which is why it's the primary method, not the stopgap.
- Don't guess the Monitor's `--session-id`: see `grand-admiral`'s `references/stall-watchdog.md` (linked from § Recovery → Built-in Stall Watchdog) for deriving `--team-dir` from a spawn's own `agent_id` instead.

## Recovering a Stale Broker

Each worktree dispatch spins up its own broker (`app-server-broker.mjs` bound to `/tmp/cxc-<id>/broker.sock`, `--cwd` = the worktree). Removing and recreating a worktree at the **same path** while its broker still runs strands a stale broker: the next `task` dispatch against that path fails instantly (~0 s) with a misleading auth-shaped error (`failed to resolve feature override precedence` / `auth.loggedIn: false`).

Recovery: find the orphaned broker PID (its `--cwd` points at the old worktree path), `kill` it, `rm -rf /tmp/cxc-<id>`, then redispatch — a fresh broker binds automatically. Exact commands: `references/sandbox-and-recovery.md` § Broker Recovery.

## Additional Resources

- **`references/sandbox-and-recovery.md`** — sandbox modes, the `workspace-write` config, on-disk job-state layout for monitoring, git-commit-in-a-worktree status (inconsistent) and its fallback, harness kills of a backgrounded task and how to resume, and copy-paste broker-recovery commands.
