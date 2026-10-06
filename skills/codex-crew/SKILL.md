---
name: codex-crew
description: "Pre-flight guide for enlisting Codex agents: model routing, direct dispatch via codex-companion.mjs, sandbox and worktree rules, job monitoring, broker recovery. This skill should be used when preparing to dispatch work to Codex Astra, deciding whether to route coding to Codex, dispatching directly via codex-companion.mjs rather than the codex:codex-rescue subagent, handling a Codex job that fails to write or commit, monitoring a running Codex job, or recovering a stale Codex broker. The coordinator reads its pre-flight guidance once before the first Codex dispatch of a session."
---

# Codex Crew — Enlisting Codex Agents

Codex agents (OpenAI Codex CLI via the `codex` plugin's `codex-companion.mjs`) are opt-in external crew alongside the claudius roster. Read once before the session's first Codex dispatch.

**Dispatch directly, never through `codex:codex-rescue`.** That subagent is pure overhead — one `Bash` call forwarding stdout, unreliable lifecycle signals, and no `--cwd`/`--prompt-file` (root cause of most bugs below). Call `codex-companion.mjs task` directly (§ Direct Dispatch). `codex:codex-rescue` stays for the user-typed `/codex:rescue`, which this skill doesn't govern.

## When to Enlist Codex

- **Opt-in, not default** — when the user asks, or per the coding preference below.
- **Coding-first (project default):** code-writing work prefers **Codex Astra** over Opus-tier claudius agents (`developer-bilby`) — an intentional override of `delegate`'s Token Economy tiering for implementation tasks.
- **Non-coding roles keep normal tiering:** review, QA, security, architecture, and docs stay with claudius agents unless the user opts them into Codex.

## Routing — Model Selection, High Effort

- **Default: Codex Astra = `--model gpt-6-astra --effort high`. Always high effort.** State both flags on every dispatch — omitting either drops to the runtime default, not Astra.
- **Security-related dispatch: `--model gpt-daybreak-blue-latest --effort high` instead of Astra, when available** — for Codex tasks that are themselves security work (audits/reviews, auth/crypto/secrets handling, vulnerability triage/remediation, dependency security review), not ordinary code that happens to touch an authenticated endpoint. Availability is unconfirmed: if the job record shows `status: failed` with an unknown-model or access-gate/auth error, redispatch the same prompt on Astra and tell the user. Never retry Daybreak Blue more than once per dispatch.
- Not the lighter `spark` alias.

## Direct Dispatch

Resolve the installed `codex` plugin's script root once per session — version-pinned cache dirs shift on plugin updates, never hardcode a version:

```bash
CODEX_ROOT=$(find ~/.claude/plugins/cache/openai-codex/codex -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)
```

Write the prompt to a file — never inline it as a shell argument (nested quotes and Rust `Debug` dumps corrupt under shell quoting). `task` accepts `--prompt-file <path>` (also reads piped stdin); a relative path resolves against `--cwd`, so always pass an **absolute** path under the coordinator's configured scratch location (e.g. `/data/tmp` on this host).

Every dispatch prompt must say near the top: **"You are a leaf worker, not a coordinator — do not load or follow grand-admiral, delegate, report-format, or severity; those apply only to sessions that spawn/manage other agents, which you are not."**

```bash
node "$CODEX_ROOT/scripts/codex-companion.mjs" task \
  --cwd <worktree-abs-path> \
  --prompt-file <scratch-abs-path>/<descriptive-name>.txt \
  --write --background \
  --model gpt-6-astra --effort high
```

Security-related task: swap the model flag per § Routing (same shape; Astra fallback on unknown-model/access-gate failure).

- **`--cwd <worktree-abs-path>` binds the broker/workspace slug to the intended worktree** — pass it on every dispatch; never rely on the shell's cwd or on prompt text telling Codex to `cd` (zero effect — rule 3).
- **`--write` is not implied** — without it the run is silently read-only (completes normally, touches zero files).
- **`--background`** returns a job id almost instantly; the coordinator polls job state (§ Monitoring a Codex Job) rather than blocking.
- **Continuing a thread:** `--resume-last` (= `--resume`) with the **identical** `--cwd` — threads are found by workspace, so a mismatched `--cwd` resumes nothing.

## Plan-Approval Gate

**Sandbox write mode is pinned when the Codex app-server creates a thread; a resume cannot escalate it.** A thread first dispatched without `--write` stayed read-only under `--resume-last --write` (`apply_patch` rejected). Never plan without `--write` then resume with it.

For a well-scoped task that might write anything, dispatch the first turn with `--write`. For a genuine approval gate on large or risky work:

1. Dispatch a read-only investigation and plan without `--write`.
2. After approval, start a **fresh job** (never `--resume-last`) with `--write`, embedding the approved plan plus any revisions in its prompt.

The fresh job rebuilds context but is the only safe read-only-to-writable boundary. `delegate` § Development-Work Delegation remains the source of truth for the coordinator's plan review.

## Sandbox & Workdir — The Load-Bearing Rules

Codex runs under `sandbox_mode = "workspace-write"` (`~/.codex/config.toml`). Three rules:

1. **Write scope = cwd + the effective `writable_roots`.** Rely on the configured worktree root (`$CLAUDIUS_WORKTREE_ROOT`; see `grand-admiral` § Worktree Isolation), scratch location, and shared cargo target dir, plus `network_access = true`. Do **not** assume the configured artifacts location is writable even when config lists it; use the coordinator-owned delivery path in `references/sandbox-and-recovery.md` § `workspace-write` Config. Paths outside cwd and the effective roots are read-only.

2. **Codex `git commit` in a linked worktree is inconsistent** — one dispatch commits cleanly, the next hits "Git metadata is read-only"/`index.lock`, with identical config. **Coordinator-commit is the reliable default:** tell Codex to attempt `git add`/`git commit` last (with an explicit message), then verify via `git log`/`git status` in the worktree — never trust its self-report — and commit yourself (unsandboxed) when it didn't land. Details: `references/sandbox-and-recovery.md` § Git Commit in a Linked Worktree.

3. **Worktrees live at `<worktree-root>/<slug>`** (`$CLAUDIUS_WORKTREE_ROOT`; default `/data/git-worktrees`; slug from the startup `$PWD`), pre-created by the coordinator per `grand-admiral` § Worktree Isolation. **The broker keys off `codex-companion.mjs`'s own resolved cwd, not any path in prompt text** — a dispatch told via prompt to `cd` into a worktree still bound to the coordinator's checkout and blocked ALL writes, even on the first dispatch. Pass the worktree via `--cwd` (§ Direct Dispatch); each `--cwd` is self-contained, so N worktrees dispatch concurrently.

### Never Dispatch Concurrently to the Same `--cwd`

**Never fire dispatch N+1 at the same `--cwd` until dispatch N's job JSON shows a terminal `status`** (`completed`/`failed`). One broker serves each workspace slug (keyed off `--cwd`), not each job; same-cwd dispatches collide even minutes apart — only polling for terminal status protects, never a fixed stagger delay. A collision silently strands the earlier job at `running` forever, or instantly returns generic capabilities boilerplate with `touchedFiles: []` (looks like a trivial done, isn't). After any dispatch, check the job's `workspaceRoot` matches the intended worktree and its `rawOutput` engages the dispatched task — a suspiciously fast, generic completion is a collision red flag. Detail: `references/sandbox-and-recovery.md` § Same-`--cwd` Collisions.

## Monitoring a Codex Job

A `--background` dispatch is a detached Node process with on-disk job-state files — no agent lifecycle to watch, nothing to shut down. (`codex:codex-rescue` `idle_notification`s are worthless: jobs sat `completed` 40–85 min before the wrapper reported.)

- **Primary method: read the job's on-disk state directly** (mtime-gated, minimal fields, never the full blob) — `references/sandbox-and-recovery.md` § On-Disk Job State.
- **Get notified, don't wait for a user request:** arm a `Bash` `run_in_background` loop on the job's own `jobs/<job-id>.json` that exits on a terminal status or a dead `pid` (script: `references/sandbox-and-recovery.md` § Monitoring Loop). The loop can itself be silently killed — periodically confirm it's alive; silence is not health.
- `ScheduleWakeup` is not a substitute (`/loop` dynamic-mode-only).
- The stall watchdog (`grand-admiral` § Recovery → Stall Watchdog) emits `CODEX_*` events — **mandatory** for every dispatch, but best-effort on top of the direct job-state check, never a substitute. **Codex discovery requires `--worktrees`** at the configured worktree root (a direct dispatch is never a teammate); without it: a one-time startup warning, then silently zero Codex monitoring. Don't guess the Monitor's `--session-id`: derive `--team-dir` from a spawn's own `agent_id` per `grand-admiral`'s `references/stall-watchdog.md`.

## Recovering a Stale Broker

Recreating a worktree at the **same path** while its broker (`app-server-broker.mjs`) still runs strands it: the next dispatch fails in ~0 s with a misleading auth-shaped error (`failed to resolve feature override precedence` / `auth.loggedIn: false`). Kill the orphaned broker, remove its `/tmp/cxc-<id>`, redispatch — commands in `references/sandbox-and-recovery.md` § Broker Recovery.

## Additional Resources

- **`references/sandbox-and-recovery.md`** — sandbox modes, `workspace-write` config, on-disk job state, monitoring loop, same-`--cwd` collisions, git-commit-in-a-worktree status and fallback, harness kills of a backgrounded task, broker recovery.
