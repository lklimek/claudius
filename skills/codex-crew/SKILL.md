---
name: codex-crew
description: Use before dispatching work to Codex (codex:codex-rescue) — deciding whether to route coding to Codex Sol, handling a Codex job that fails to write or commit, monitoring a running Codex job, or recovering a stale Codex broker. Pre-flight the coordinator reads once before its first Codex dispatch of a session.
---

# Codex Crew — Enlisting Codex Agents

Codex agents (OpenAI Codex CLI, dispatched through `codex:codex-rescue`) are external crew a coordinator can enlist alongside the named claudius roster. Use of Codex is **opt-in**. Read this once before the first Codex dispatch of a session — it covers routing, the sandbox's hard limits, how to monitor a Codex job, and how to recover a stuck broker.

The recurring failure this skill prevents: coordinators re-derive the same Codex sandbox and orchestration quirks session after session, each losing time to the same write-rejection and broker-staleness traps (and an inconsistent commit path — see Sandbox & Workdir rule 2).

## When to Enlist Codex

- **Opt-in, not the default.** Reach for Codex when the user asks for it, or per the standing coding preference below.
- **Coding-first (project default).** Actual code-writing work prefers **Codex Sol** over Opus-tier claudius agents (`developer-bilby`). This intentionally overrides `spawn-checklist`'s Token Economy model tiering for implementation tasks.
- **Non-coding roles keep normal tiering.** Review, QA, security, architecture, and docs stay with their claudius agents unless the user explicitly opts them into Codex.

## Routing — One Model, High Effort

- **Codex Sol = `--model gpt-5.6-sol --effort high`. Always high effort.** State both flags explicitly on every dispatch: `codex:codex-cli-runtime` only forwards `--effort`/`--model` when present in the request text, so an omitted flag silently drops to the runtime default.
- **Dispatch through `codex:codex-rescue`.** It is a thin forwarder: exactly one `task` invocation, returning that stdout unchanged. It does **not** monitor, poll, or fetch results on its own initiative — that's **coordinator** work (see Monitoring below). It CAN attempt a commit when the dispatch prompt explicitly instructs it to, but success is inconsistent; the coordinator must verify independently (see Sandbox & Workdir rule 2).
- The lighter `spark` alias (`gpt-5.3-codex-spark`) exists, but claudius routing standardizes on Sol at high effort.

## Sandbox & Workdir — The Load-Bearing Rules

Codex runs under `sandbox_mode = "workspace-write"` (see `~/.codex/config.toml`). Three rules carry all the weight:

1. **Write scope = cwd + configured `writable_roots`.** On this host `writable_roots` includes the worktree root (`$CLAUDIUS_WORKTREE_ROOT`; see `grand-admiral` § Worktree Isolation), `/data/tmp`, `/data/artifacts`, `/data/target` (the shared cargo target dir), plus `network_access = true`. So worktrees under `$CLAUDIUS_WORKTREE_ROOT/<slug>` **are** writable by Codex, scratch under `/data/tmp` and `/data/artifacts` is writable, cargo build output under `/data/target` is writable, and sandboxed tests **can** bind localhost sockets. Paths outside cwd and `writable_roots` are read-only. `scripts/cargo-cached.sh`'s verification ledger handles this on its own: when the default `~/.cache/claudius/ledger` root is unreachable from inside the sandbox, it falls back to a workspace-local directory rather than hard-failing (the script remains the source of truth for the mechanism).

2. **Codex `git commit` in a linked worktree is inconsistent — confirmed both ways the same day (2026-07-16).** One dispatch committed cleanly (`f2639aa`, this repo, no approval prompt). A later dispatch, same repo, different worktree, hit the exact old "Git metadata is read-only"/`index.lock` error and had to be committed by the coordinator instead (`7c2d3e8`). `writable_roots` was unchanged across both, so whatever gates this isn't a static config value — likely `approval_policy = "on-request"` + `trust_level = "trusted"` interacting with something per-dispatch, not independently confirmed. **Treat coordinator-commit as the reliable default, not a fallback**: it is fine to instruct Codex to attempt `git add`/`git commit` itself as its final step (with an explicit commit message — it doesn't know your conventions unless told), but always plan for that attempt to fail and verify afterward — check `git log`/`git status` in the worktree rather than trusting Codex's self-report, and commit yourself (unsandboxed) when it didn't land. See `references/sandbox-and-recovery.md` § Git Commit in a Linked Worktree for both data points.

3. **All worktrees live under the configured root** (`$CLAUDIUS_WORKTREE_ROOT`, default `.claude/worktrees`) at `<worktree-root>/<slug>`, where the slug derives from the startup `$PWD`. The coordinator pre-creates the worktree following the isolation pattern in `grand-admiral` § Worktree Isolation — which owns the pre-create-and-inject-absolute-path procedure — and injects that absolute path into the dispatch.

Deep mechanics (exact sandbox modes, the on-disk job-state layout, `git commit` in a linked worktree status and fallback) are in `references/sandbox-and-recovery.md`.

### Never Dispatch Back-to-Back from the Same cwd

**Stagger concurrent Codex dispatches.** `codex:codex-rescue` keys its broker and workspace slug off the **invoking session's cwd**, not the `--worktree` path carried in the dispatch prompt — so two dispatches fired from one session cwd collide on a single slug even when they target different worktrees. The second dispatch's broker startup tears down the first's in-flight turn, which then sits at `status=running` forever and emits no completion signal: a silent orphan, not a visible failure. The root cause lives in the separate `openai-codex` plugin and cannot be fixed from this repo.

Mitigation: stagger dispatches, or verify each dispatch has its own dedicated broker before firing the next. `scripts/agent-watchdog.py` should eventually catch the resulting hang as `CODEX_STALL reason=no-progress` — a detection backstop, not a substitute for avoiding the collision.

## Monitoring a Codex Job

**`codex:codex-rescue` gives no reliable completion heartbeat.** It emits at most one early `idle_notification` (often while still writing prep files, before the real work starts) and then nothing when it finishes — a confirmed blind spot that has left completed Codex output unnoticed for over an hour in mixed Claude+Codex panels. **Never rely on `idle_notification` or a teammate-message to learn a Codex job finished.**

Instead, monitor Codex progress the same way the stall watchdog monitors Claude agents — from on-disk job state, not from harness signals:

- The stall watchdog (`grand-admiral` § Recovery → `scripts/agent-watchdog.py`) discovers Codex jobs and emits `CODEX_*` transition events. Launching it is **mandatory** whenever any agent — Claude or Codex — is dispatched (see `grand-admiral` § Spawning → Monitoring).
- **Codex discovery is gated on team membership or `--worktrees`.** The watchdog reaches Codex jobs only through named teammates or an explicit `--worktrees` path on the Monitor command. A session whose Codex work is entirely unnamed background `codex:codex-rescue` dispatches, launched without `--worktrees`, gets **zero** Codex monitoring — the watchdog emits a one-time startup warning on detecting this. Either name Codex dispatches so they join the team, or always point the Monitor command's `--worktrees` flag at the configured worktree root.
- As a manual stopgap when the watchdog is not running, poll the job's on-disk state directly (mtime-gated, minimal-field reads — never load the full state blob): see `references/sandbox-and-recovery.md` § On-Disk Job State.

## Recovering a Stale Broker

Each worktree dispatch spins up its own broker (`app-server-broker.mjs` bound to `/tmp/cxc-<id>/broker.sock`, `--cwd` = the worktree). Removing and recreating a worktree at the **same path** while its broker still runs strands a stale broker: the next `task` dispatch against that path fails instantly (~0 s) with a misleading auth-shaped error (`failed to resolve feature override precedence` / `auth.loggedIn: false`).

Recovery: find the orphaned broker PID (its `--cwd` points at the old worktree path), `kill` it, `rm -rf /tmp/cxc-<id>`, then redispatch — a fresh broker binds automatically. Exact commands: `references/sandbox-and-recovery.md` § Broker Recovery.

## Additional Resources

- **`references/sandbox-and-recovery.md`** — sandbox modes, the `workspace-write` config, on-disk job-state layout for monitoring, git-commit-in-a-worktree status (inconsistent) and its fallback, harness kills of a backgrounded task and how to resume, and copy-paste broker-recovery commands.
