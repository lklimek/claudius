# Codex Sandbox, Job State & Recovery — Reference

Deep mechanics behind `codex-crew`. Load when a Codex job misbehaves (write rejected, commit blocked, dispatch fails instantly) or when hand-monitoring a job.

## Sandbox Modes

Codex CLI supports three sandbox modes:

| Mode | Behavior |
|---|---|
| `read-only` (default / review) | No writes; used for review/diagnosis runs. |
| `workspace-write` | Writes allowed under cwd + configured `writable_roots`; network disabled unless `network_access = true`. `codex:codex-rescue` uses this for `--write` tasks. |
| `danger-full-access` | No sandbox. Not used by claudius dispatch. |

## `workspace-write` Config (this host)

`~/.codex/config.toml`:

```toml
sandbox_mode = "workspace-write"
model = "gpt-5.6-sol"
model_reasoning_effort = "high"

[sandbox_workspace_write]
writable_roots = ["/data/git-worktrees", "/data/tmp", "/data/artifacts"]
network_access = true
```

- `writable_roots` **adds** to the always-writable workspace root (cwd). It makes `/data` worktrees + scratch writable and lets tests reach the network.
- `network_access = true` unblocks localhost test sockets (e.g. a test server) — it also enables general outbound network, the tradeoff `workspace-write` disables by default.
- Validate any change with `codex --strict-config doctor` (hard-errors on unknown fields). Keep a timestamped backup of `config.toml` before editing.

## Why Codex Cannot `git commit` in a Linked Worktree

Two stacked restrictions, both confirmed across sessions:

1. **Path allowlist.** A linked worktree created by `git worktree add /data/git-worktrees/foo` from main repo `/home/ubuntu/git/<repo>` stores its per-worktree git metadata (HEAD, index, refs) under the **main repo's** `.git/worktrees/foo/`, and objects under the main repo's `.git/objects/`. Those paths are outside the sandbox's writable set, so `git commit` (which writes `index.lock`, refs, objects there) is rejected.
2. **Git-metadata block.** A separate read-only block on git metadata applies **even when the path is writable**, so widening `writable_roots` to include the repo `.git` is not a reliable fix.

**Consequence — coordinator commits.** Do not try to make Codex commit. Codex writes source changes into the worktree; the coordinator (unsandboxed) then runs `git -C <worktree> add -A && git -C <worktree> commit -m ...`. Verify Codex's diff before committing on its behalf.

Symptom when Codex tries anyway: a job `errorMessage` such as *"the sandbox prevented creating the requested commit because the worktree's Git metadata is read-only"*, or a git error about being unable to create `index.lock` under the main repo's external `.git`.

## On-Disk Job State (for Monitoring)

Codex job state lives under `$CLAUDE_PLUGIN_DATA/state/` (default `CLAUDE_PLUGIN_DATA=/home/ubuntu/.claude/plugins/data/codex-openai-codex`), one directory per workspace:

```
state/<workspace-slug>-<hash>/
  broker.json            # broker endpoint + cwd (workspaceRoot)
  state.json             # {version, config, jobs:[...]}  — embeds ALL jobs; grows unbounded
  jobs/<job-id>.json     # per-job record (small)
  jobs/<job-id>.log      # streamed progress + final result / error text
```

Per-job `.json` fields worth reading: `id`, `status` (`pending` | `running` | `completed` | `failed`), `phase`, `errorMessage`, `startedAt`, `completedAt`, `workspaceRoot`, `logFile`. `pid` is often `null` (jobs run inside the shared app-server, not as a tracked child).

**Memory discipline (long sessions).** The watchdog polls repeatedly. Do **not** parse `state.json` per poll — it embeds every job and grows over the session. Instead:

- Use the newest mtime under `jobs/` (or `state.json`'s mtime) as the cheap **activity clock**.
- Parse an individual `jobs/<id>.json` only when its mtime advanced since the last poll, and extract only the few fields above.
- Keep a bounded per-job last-seen map (`job-id → {status, mtime}`), never accumulated JSON.

Map a monitored worktree to its state dir by matching a job's `workspaceRoot` (or `broker.json`'s cwd) to the worktree path. `status: failed` with an `errorMessage` is the signal to surface — that is exactly the class (e.g. the commit block above) that otherwise goes unnoticed.

`codex exec --json` also emits a JSONL event stream (`thread.started`, `turn.completed`, `item.completed`, `error`) for foreground runs — an alternative progress signal when not going through the companion's job state.

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

Prefer namespacing/avoiding worktree remove+recreate at an identical path during an active session; when unavoidable, recover the broker first.
