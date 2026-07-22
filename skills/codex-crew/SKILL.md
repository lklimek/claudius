---
name: codex-crew
description: Use before dispatching work to Codex (codex:codex-rescue) — deciding whether to route coding to Codex Sol, handling a Codex job that fails to write or commit, monitoring a running Codex job, or recovering a stale Codex broker. Pre-flight the coordinator reads once before its first Codex dispatch of a session.
---

# Codex Crew — Enlisting Codex Agents

Codex agents (OpenAI Codex CLI, dispatched through `codex:codex-rescue`) are external crew a coordinator can enlist alongside the named claudius roster. Use of Codex is **opt-in**. Read this once before the first Codex dispatch of a session — it covers routing, the sandbox's hard limits, how to monitor a Codex job, and how to recover a stuck broker.

The recurring failure this skill prevents: coordinators re-derive the same Codex sandbox and orchestration quirks session after session, each losing time to the same write-rejection and broker-staleness traps (and an inconsistent commit path — see Sandbox & Workdir rule 2).

## When to Enlist Codex

- **Opt-in, not the default.** Reach for Codex when the user asks for it, or per the standing coding preference below.
- **Coding-first (project default).** Actual code-writing work prefers **Codex Sol** over Opus-tier claudius agents (`developer-bilby`). This intentionally overrides `delegate`'s Token Economy model tiering for implementation tasks.
- **Non-coding roles keep normal tiering.** Review, QA, security, architecture, and docs stay with their claudius agents unless the user explicitly opts them into Codex.

## Routing — One Model, High Effort

- **Codex Sol = `--model gpt-5.6-sol --effort high`. Always high effort.** State both flags explicitly on every dispatch: `codex:codex-cli-runtime` only forwards `--effort`/`--model` when present in the request text, so an omitted flag silently drops to the runtime default.
- **Dispatch through `codex:codex-rescue`.** It is a thin forwarder: exactly one `task` invocation, returning that stdout unchanged. It does **not** monitor, poll, or fetch results on its own initiative — that's **coordinator** work (see Monitoring below). It CAN attempt a commit when the dispatch prompt explicitly instructs it to, but success is inconsistent; the coordinator must verify independently (see Sandbox & Workdir rule 2).
- The lighter `spark` alias (`gpt-5.3-codex-spark`) exists, but claudius routing standardizes on Sol at high effort.

## Plan-Approval Gate

Codex dispatches follow `grand-admiral` § Development-Work Delegation: goal only, no file list, agent-authored plan approved by the coordinator before writing code. Split into two dispatches on the SAME Codex thread, never two independent ones — a fresh dispatch rebuilds context from scratch, which is exactly the cost this gate must not add. Sequence:

0. **`EnterWorktree(path=<worktree-abs-path>)` before either dispatch** (see Sandbox & Workdir rule 3) — `--resume` finds the thread by workspace, so both dispatches must bind to the identical cwd or the implement dispatch resumes nothing.
1. **Plan dispatch**: request read-only investigation and a plan, no edits (`codex:codex-rescue` defaults to write-capable — say so explicitly to get a no-writes run).
2. **Implement dispatch**: after approval, dispatch with `--resume` (`codex:codex-cli-runtime` maps this to `task --resume-last`, continuing the same per-workspace thread) carrying only the delta instruction ("approved — implement as planned", or the requested changes) — never a restated prompt.

**Known risk — a failed `--resume` can silently duplicate work.** Observed: a `--resume` dispatch fails instantly (`CODEX_FAILED "No previous Codex task thread was found for this repository"`) yet keeps running in the background despite the terminal-failure report, and later lands a second job with its own (redundant) output. If step 2 reports a `--resume` failure, do NOT immediately fire a `--fresh` redispatch from the same cwd — check job state first (§ Monitoring a Codex Job) to rule out a still-running duplicate before treating the cwd as free. Root cause open (`memcan:todo` project=claudius).

## Sandbox & Workdir — The Load-Bearing Rules

Codex runs under `sandbox_mode = "workspace-write"` (see `~/.codex/config.toml`). Three rules carry all the weight:

1. **Write scope = cwd + configured `writable_roots`.** On this host `writable_roots` includes the worktree root (`$CLAUDIUS_WORKTREE_ROOT`; see `grand-admiral` § Worktree Isolation), `/data/tmp`, `/data/artifacts`, `/data/target` (the shared cargo target dir), plus `network_access = true`. So worktrees under `$CLAUDIUS_WORKTREE_ROOT/<slug>` **are** writable by Codex, scratch under `/data/tmp` and `/data/artifacts` is writable, cargo build output under `/data/target` is writable, and sandboxed tests **can** bind localhost sockets. Paths outside cwd and `writable_roots` are read-only. `scripts/cargo-cached.sh`'s verification ledger handles this on its own: when the default `~/.cache/claudius/ledger` root is unreachable from inside the sandbox, it falls back to a workspace-local directory rather than hard-failing (the script remains the source of truth for the mechanism).

2. **Codex `git commit` in a linked worktree is inconsistent — confirmed both ways the same day (2026-07-16).** One dispatch committed cleanly (`f2639aa`, this repo, no approval prompt). A later dispatch, same repo, different worktree, hit the exact old "Git metadata is read-only"/`index.lock` error and had to be committed by the coordinator instead (`7c2d3e8`). `writable_roots` was unchanged across both, so whatever gates this isn't a static config value — likely `approval_policy = "on-request"` + `trust_level = "trusted"` interacting with something per-dispatch, not independently confirmed. **Treat coordinator-commit as the reliable default, not a fallback**: it is fine to instruct Codex to attempt `git add`/`git commit` itself as its final step (with an explicit commit message — it doesn't know your conventions unless told), but always plan for that attempt to fail and verify afterward — check `git log`/`git status` in the worktree rather than trusting Codex's self-report, and commit yourself (unsandboxed) when it didn't land. See `references/sandbox-and-recovery.md` § Git Commit in a Linked Worktree for both data points.

3. **All worktrees live under the configured root** (`$CLAUDIUS_WORKTREE_ROOT`, default `.claude/worktrees`) at `<worktree-root>/<slug>`, where the slug derives from the startup `$PWD`. The coordinator pre-creates the worktree following the isolation pattern in `grand-admiral` § Worktree Isolation. **Injecting the absolute path into the dispatch prompt text is not enough** — confirmed 2026-07-21: a dispatch instructed to `cd` into a pre-created worktree still bound its broker to the coordinator's plain checkout, blocking ALL writes (including under `writable_roots`) even on the FIRST dispatch, because the broker keys off the invoking session's actual `$PWD`, not any path mentioned in prompt text. Fix: call `EnterWorktree(path=<worktree-abs-path>)` to physically move the coordinating session into the worktree BEFORE dispatching — do this even for a single, non-concurrent dispatch. Leave with `ExitWorktree(action="keep")` (never `"remove"` — the worktree may hold uncommitted work) before entering a different worktree for the next stream.

Deep mechanics (exact sandbox modes, the on-disk job-state layout, `git commit` in a linked worktree status and fallback) are in `references/sandbox-and-recovery.md`.

### Never Dispatch Back-to-Back from the Same cwd

**Never fire dispatch N+1 from a cwd whose dispatch N hasn't reached a terminal job status.** Same root cause as rule 3 above: `codex:codex-rescue` keys its broker and workspace slug off the **invoking session's cwd**, not the `--worktree` path carried in the dispatch prompt — so two dispatches fired from one session cwd collide on a single slug even when they target different worktrees, even minutes apart. `EnterWorktree` fixes cwd binding for one stream at a time; it does not make two dispatches from the same coordinator session concurrency-safe. Confirmed: dispatches 6–9 minutes apart still collided, and elapsed time or a prior dispatch already having its own job-state file were NOT protective — the only safe rule is polling that dispatch N's job JSON shows `status` in `completed`/`failed` before firing N+1 from that cwd. A collision either strands the earlier dispatch at `status=running` forever with no completion signal (silent orphan), or — observed separately — the earlier dispatch instantly returns Codex's generic capabilities boilerplate with `touchedFiles: []` as if it never received the real prompt (looks like a trivial done, isn't). The root cause lives in the separate `openai-codex` plugin and cannot be fixed from this repo.

Mitigation: poll for terminal job status before the next dispatch from a given cwd (never a fixed stagger delay). `scripts/agent-watchdog.py` should eventually catch a stuck orphan as `CODEX_STALL reason=no-progress` — a detection backstop, not a substitute for avoiding the collision. After any dispatch, sanity-check the job's `workspaceRoot` matches the intended worktree and its `rawOutput` actually engages the dispatched task — a suspiciously fast, generic-sounding completion is a collision red flag, not evidence the task was trivial.

## Monitoring a Codex Job

**MCP watchdog covers Codex too** (`runtime: codex_cli`/`codex_companion` in `register_session`) — prefer it over the `CODEX_*` machinery below when available (see `grand-admiral` § Recovery → MCP Watchdog), with the same corroborate-before-acting caution.

**`codex:codex-rescue` gives no reliable completion heartbeat, in either direction.** `idle_notification` fires as a false-early signal while the job is still genuinely working, AND separately fails to fire at all once real work — including a silent engine crash — has already finished; confirmed 4-for-4 in one wave, with jobs sitting `completed` 40–85 minutes before their wrapper ever reported. **Never treat `idle_notification`, or the absence of a message, as a status signal in either direction.**

**Primary method: read the job's on-disk state directly** (mtime-gated, minimal-field reads — never load the full state blob). See `references/sandbox-and-recovery.md` § On-Disk Job State for the field list, `result.rawOutput`/`result.touchedFiles` usage, and matching jobs to dispatches. This is load-bearing, not a fallback — it is what actually recovers status/results when the stall watchdog can't.

**Get notified, don't just poll on request.** After ruling out a false-early `idle_notification`, arm a `Bash` `run_in_background` until-loop on that job's own `state/<workspace-slug>-<hash>/jobs/<job-id>.json` (resolve the path per § On-Disk Job State above) — a single, job-specific completion signal that needs no team/session discovery:

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

- The built-in stall watchdog (`grand-admiral` § Recovery → Built-in Stall Watchdog, `scripts/agent-watchdog.py`) discovers Codex jobs and emits `CODEX_*` transition events when the MCP watchdog isn't in use. A watchdog — MCP or built-in — is **mandatory** whenever any agent — Claude or Codex — is dispatched (see `grand-admiral` § Spawning → Monitoring). Treat its `CODEX_*` events as **best-effort, layered on top of** the direct job-state check above — never as a substitute for it.
- **Codex discovery is gated on team membership or `--worktrees`.** The watchdog reaches Codex jobs only through named teammates or an explicit `--worktrees` path on the Monitor command. A session whose Codex work is entirely unnamed background `codex:codex-rescue` dispatches, launched without `--worktrees`, gets **zero** Codex monitoring — the watchdog emits a one-time startup warning on detecting this. Either name Codex dispatches so they join the team, or always point the Monitor command's `--worktrees` flag at the configured worktree root.
- **Direct discovery (`--worktrees`/Source C) now bypasses the session gate entirely** — a workspace found under the worktree root surfaces every job's `CODEX_*` events regardless of `sessionId`, closing the multi-teammate blind spot as long as the Monitor's `--worktrees` points at the configured root (see bullet above). The strict single-session match still applies to *ambient* discovery only (a workspace reachable solely via team lead/member cwd, not also under the worktree root) — `codex-companion.mjs` stamps each job's `sessionId` from its own dispatching session, never the coordinator's, so that narrower path can still under-report a mismatched session. The direct job-state check above is unaffected by any of this either way, which is why it's the primary method, not the stopgap.
- Don't guess the Monitor's `--session-id`: see `grand-admiral`'s `references/stall-watchdog.md` (linked from § Recovery → Built-in Stall Watchdog) for deriving `--team-dir` from a spawn's own `agent_id` instead.

## Recovering a Stale Broker

Each worktree dispatch spins up its own broker (`app-server-broker.mjs` bound to `/tmp/cxc-<id>/broker.sock`, `--cwd` = the worktree). Removing and recreating a worktree at the **same path** while its broker still runs strands a stale broker: the next `task` dispatch against that path fails instantly (~0 s) with a misleading auth-shaped error (`failed to resolve feature override precedence` / `auth.loggedIn: false`).

Recovery: find the orphaned broker PID (its `--cwd` points at the old worktree path), `kill` it, `rm -rf /tmp/cxc-<id>`, then redispatch — a fresh broker binds automatically. Exact commands: `references/sandbox-and-recovery.md` § Broker Recovery.

## Additional Resources

- **`references/sandbox-and-recovery.md`** — sandbox modes, the `workspace-write` config, on-disk job-state layout for monitoring, git-commit-in-a-worktree status (inconsistent) and its fallback, harness kills of a backgrounded task and how to resume, and copy-paste broker-recovery commands.
