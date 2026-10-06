---
name: delegate
description: "This skill should be used before delegating work to an agent — one Agent() spawn or a whole wave — and when the user says \"spawn an agent\", \"delegate this\", \"parallelize this\", \"split this work\", or \"use a subagent\". It covers the spawn decision (inline vs spawn, model tier, batching), what every agent prompt must contain, WHAT-not-HOW briefing of development work including the one-agent plan/TDD/implement/self-review loop for changes up to 1000 LOC, and durable tracking of delegated or multi-step work that survives compaction."
---

# Delegate

Load before the first `Agent()` call of a session; re-read after compaction. Spawning is the dominant token cost: every subagent rebuilds its context cache from scratch. The cheapest work is the spawn that never happens.

## Pre-Delegation Checklist

1. **Total scope size** — sum the estimated diff (excluding comments) across the whole batch, not per item. Under ~300 lines total (soft): do it in the coordinator, or fold into an agent already live in scope via `SendMessage`; do not spawn.
2. **Genuine parallelism** — a real wall-clock or file-independence need, or would sequential merely take "a bit longer"? No real need → one agent, sequential. Tightly coupled cross-file work → one agent, never a parallel split.
3. **Reuse** — an agent already live in the same file/domain scope? → `SendMessage` it (`grand-admiral` § Agent Reuse).
4. **Model tier** — set explicitly on this spawn (§ Token Economy); never leave it to the frontmatter fallback.
5. **Worktree** — code-mutating agents: pre-create it and inject the resolved SHA; never rely on `isolation: "worktree"` (`grand-admiral` § Worktree Isolation).
6. **Monitoring** — is the stall watchdog running? An un-monitored dispatch is a doctrine violation (`grand-admiral` § Recovery → Stall Watchdog).
7. **Development work?** — brief the goal only (§ Development-Work Delegation).
8. **Tracked?** — one entry per dispatched unit in the durable file (§ Tracking).

**Anti-pattern — file-independence is not spawn-justification.** Four doc-only fixes, each under 20 lines in its own file, got four Opus spawns — the batch belonged to one agent. Independent files justify a separate worktree or commit, NOT automatically a separate agent.

## Token Economy

1. **Spawn discipline**: inline small/sequential work in the warm parent context. Spawn ONLY for genuinely parallel independent work, large scope (~20k+ output tokens, many files), or required context isolation.
2. **Model tiering (mandatory)**: set the model on every spawn — frontmatter `model:` is only the fallback. `sonnet` is the default workhorse. Tier by where quality is load-bearing:
   - **Opus** — quality-critical reasoning/agentic depth: `developer-bilby`, `project-reviewer-adams`, `architect-nagatha`, `ux-designer-diziet`, `security-engineer-smythe` (their frontmatter fallback).
   - **Sonnet** — agentic-but-routine: the coordinator, `qa-engineer-marvin` (adversarial QA execution), `technical-writer-trillian`, `Explore`/`general-purpose` (search), terminal/GUI/browser-automation verification.
   - **Haiku** — trivial mechanical (bulk search, formatting).

   Override per task both ways: downgrade a quality-critical agent for a trivial job; upgrade a routine agent for a genuinely hard one. **Security always escalates to Opus**: crypto, auth/key handling, network/transport, deserialization, untrusted input, dependency/version bumps, or a large/opaque diff. A passing vulnerability scan is NOT evidence of low risk; ALWAYS fully investigate a version bump, including the dependency's changed code. Cost breaks ties only among non-security work — when unsure, tier up.
3. **Read discipline**: Grep/Glob first, Read with offset/limit. Delegate unavoidably large fetches to a disposable sonnet subagent that returns a summary (`git-and-github` § Context Management).
4. **Coordinator context**: the inline-vs-spawn axis is bounded-vs-bulk, not small-vs-large. Inline only BOUNDED work; anything pulling in bulk or unbounded data (large files, logs, wide searches) goes to a disposable subagent so those bytes never enter the coordinator's context. For long sessions, summarise completed work to the tracking file and rely on compaction rather than carrying full history.

## Scaling

**Splitting:** large tasks (50+ files) → multiple agents of the same type with different file scopes by package/module/layer.

**Batching:** merge small tasks so each agent gets roughly 300+ lines of work (soft target; a small follow-up to a live agent is still fine via `SendMessage`). Respect specialization boundaries — don't merge frontend with backend, security with docs, or unrelated domains; group by same layer, language, agent type.

## Agent Prompt Requirements

Agents have NO conversation history. Every prompt MUST include:

1. **Role/scope** — what to do, focus area. Development work: goal and acceptance criteria only (§ Development-Work Delegation).
2. **File list** — explicit paths or globs; except development work, where the agent locates files itself.
3. **Output format** — structure, severity, where to write. Standalone agents write to `<tmpdir>/<agent-name>-report.md` (session dir: `mktemp -d /tmp/claudius-XXXXXX`); named teammates report via `SendMessage`. Each agent reports skills used.
4. **Constraints** — what NOT to do.
5. **Context digest** — goal, non-goals, operational profile (invocation, concurrency reality, failure cost, each with evidence), UX/DX priorities; `review-pr` § Context Digest. Unevidenced fields are `unknown`, never guessed.
6. **Change visibility** — how to see what changed: `git diff` AND `git status` (untracked files are invisible to `git diff HEAD`), `git show`, or explicit paths.
7. **Worktree base sync** (code-mutating) — absolute worktree path plus a resolved SHA and `git merge --ff-only <sha>` as first action; never a branch name or symbolic ref (`grand-admiral` § Worktree Isolation).
8. **Prior knowledge** — MemCan results relevant to the task (§ MemCan Context Injection).
9. **Bug/diagnosis tasks** — quote the user's exact reproduction steps and the literal entry point (button/command); instruct "trace from this entry point; if you can't reproduce the observed symptom, you haven't found the cause — see `bug-investigation`".
10. **Coding standards** — any agent that writes, modifies, reviews, or tests code is told to apply `coding-best-practices` throughout; it is preloaded via frontmatter, but state it so the agent applies it as it works.
11. **Cargo scope** (code agents) — name the narrowest cargo scope allowed (`-p` covering its files) and brief the OUTCOME ("clippy clean and tests green for `-p X`"), never a command chain. Require the ledger evidence line (command, tree key, exit, log path) and the provenance check in the report (`grand-admiral` § Verification Economy). Workspace-wide runs only for real cross-cutting regression risk.
12. **Executable brief** — require only actions the agent's frontmatter tools support. An agent without Task/Agent cannot invoke another agent — tell it to "apply the `plugin-dev:skill-reviewer` rubric directly (read `plugin-dev/agents/skill-reviewer.md`)", not to run that agent.
13. **Reporting channel** — state that the agent is always a subagent, never the top-level session: inline assistant text reaches no coordinator. Give the exact `to:` value (the coordinator's identity, or `team-lead`); `to:"main"` is rejected for a named subagent and has orphaned full reports. A correctly addressed agent that goes silent is not necessarily idle — `grand-admiral` § Recovery → Reporting Channel Failures.

### MemCan Context Injection

Before spawning (skip for trivial tasks): `search(query="<2-4 keywords: domain terms, API names, error text>", project="<repo>")` — the MCP tool directly, not the save/dedup workflow `lessons-learned` owns. Keep score ≥ 0.7, max 5; inject as `## Prior Knowledge (from MemCan)`, one bullet per memory: `- <memory text> [id: <short-id>]`. Injection reaches every agent; an agent's own MemCan access depends on its frontmatter tools and has been missing even on a `Tools: *` agent.

## Development-Work Delegation (WHAT, not HOW)

Applies to actual coding work (Bilby, or Codex per `codex-crew`'s dev-preference routing). Review, QA, security, docs, and UX delegation keep the file-list briefing above.

- **Stay high-level.** Brief the goal, acceptance criteria, and Prior Knowledge from Requirements/UX/architecture docs — no file list or approach; don't read source to build one. A trivial one-file/one-grep lookup is fine inline.
- **Evidence is not a verdict.** Logs plus a suspected cause are useful, but label the cause a hypothesis and tell the agent to verify or refute it before proposing implementation. Never ask an agent to implement a coordinator hypothesis on faith.
- **Coordinator selects the gate.** A named Claude teammate investigates, returns an implementation plan (files, approach, sequence), and pauses for approval via `SendMessage`. Codex: dispatch well-scoped work directly with `--write`; large or risky work uses a read-only plan then a fresh writable job — `codex-crew` § Plan-Approval Gate.
- **Review scope**: requirements fit, architecture fit, conflicts with other in-flight agents — not implementation correctness (QA's job afterward).
- **User involvement**: only when the plan is genuinely ambiguous/high-stakes, or on explicit request — otherwise approve or send back revisions autonomously.
- **Docs you rely on but never author**: Requirements, UX spec, architecture/Dev Plan. Missing or stale → delegate the update (`ux-designer-diziet` for requirements/UX, `architect-nagatha` for architecture) in the same session before proceeding.

### Single-Agent Loop (bug fix or change ≤1000 LOC)

One high-capability agent (`opus`, `fable`, or Codex at high effort; follow any standing dev-routing preference — never a lightweight tier) runs the whole cycle unattended, with no phase handoffs and no separate QA pass. Put the loop in its brief:

1. **Plan** — investigate, decide the approach, note it briefly before writing code.
2. **TDD** — tests first; they must fail before implementation.
3. **Implement** — until tests pass.
4. **Self-review** the full diff: correctness, edge cases, duplication, comment discipline, formatting/linting (`coding-best-practices`). General review, not `grumpy-review`.
5. **Self-fix, then repeat 4–5** until a pass finds nothing new; cap at 5 passes, then stop and report the remainder.

Out-of-scope findings go in the final report, never fixed inline. Ambiguous requirement, no reproduction, or a capped loop → surface to the coordinator rather than guess. The agent commits everything before exiting; the coordinator pushes. Final report: approach, tests added, self-review passes, fixes applied, what was left out of scope.

## Tracking

An in-context checklist dies on compaction — exactly how multi-task work silently drops tasks. Applies to solo, delegated, and multi-agent work alike.

- **In-session**: a plain file outside any git tree and outside anything wipeable (not `/tmp`). One entry per logical unit (dispatch, phase, file group) before starting; update as units start, complete, or block; **after compaction or any context loss re-read it** — never assume the in-context view is complete.
- **Cross-session / cross-project**: `memcan:todo` only for work that must survive a `/clear` or restart, or spans projects. Scope by `project` = repo short name from `git remote get-url origin`; `list_todos(project=<repo>, status="pending")` at session start recovers what a previous session left.

## Scope

This skill owns the spawn: whether, how many, at which tier, with what brief, tracked where. Coordinator-only doctrine — session protocol, worktree mechanics, teammates, recovery, programme management — lives in `grand-admiral`. Any agent holding a Task tool can spawn, so this skill stands alone and assumes no `grand-admiral` load.
