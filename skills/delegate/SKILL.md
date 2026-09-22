---
name: delegate
description: "This skill should be used when preparing to delegate any task to an agent — a single Agent() spawn or a whole wave — or when the user says \"spawn an agent\", \"delegate this\", \"parallelize this\", \"split this work\", or \"use a subagent\". It also applies when choosing a model tier, batching small tasks, or deciding inline-vs-spawn. Reload before every delegation, not once per session."
---

# Delegate

Run before every `Agent()` call — cheap enough to reload each time. Spawning is the dominant token cost: every subagent rebuilds its context cache from scratch, and cache creation, not model output, is the bulk of the bill. The cheapest work is the spawn that never happens.

## Pre-Delegation Checklist

1. **Total scope size** — sum the estimated diff (excluding comments) across the whole batch, not per item. Under ~300 lines total (soft): do it in the coordinator, or fold into an agent already live in scope via `SendMessage`; do not spawn.
2. **Genuine parallelism** — a real wall-clock or file-independence need, or would sequential merely take "a bit longer"? No real need → one agent, sequential.
3. **Reuse** — an agent already live in the same file/domain scope? → `SendMessage` it (`grand-admiral` § Agent Reuse).
4. **Model tier** — set explicitly on this spawn per the table below; never leave it to the frontmatter fallback.
5. **Worktree** — code-mutating agents: pre-create it and inject the resolved SHA; never rely on `isolation: "worktree"` (`grand-admiral` § Worktree Isolation).
6. **Monitoring** — is the built-in Monitor running? An un-monitored dispatch is a doctrine violation (`grand-admiral` § Recovery → Stall Watchdog).
7. **Development work?** — brief the goal only, no file list/approach; the agent plans, the coordinator approves (`grand-admiral` § Development-Work Delegation).

**Anti-pattern — file-independence is not spawn-justification.** Real case: four doc-only fixes, each under 20 lines in its own file, got four Opus spawns — the batch belonged to one agent. Independent files justify a separate worktree or commit, NOT automatically a separate agent.

## Token Economy

1. **Spawn discipline**: inline small/sequential work in the warm parent context. Spawn ONLY for genuinely parallel independent work, large scope (~20k+ output tokens, many files), or required context isolation.
2. **Model tiering (mandatory)**: set the model on every spawn — frontmatter `model:` is only the fallback. **Sonnet 5** (`sonnet` alias) is the default workhorse: ~91% of Opus on SWE-bench Pro, best-in-class terminal/computer use, strong self-verification, native 1M context, ~1.67× cheaper than Opus. Tier by where quality is load-bearing:
   - **Opus** — quality-critical reasoning/agentic depth: `developer-bilby`, `project-reviewer-adams`, `architect-nagatha`, `ux-designer-diziet`, `security-engineer-smythe` (their frontmatter fallback).
   - **Sonnet 5** — agentic-but-routine: the coordinator, `qa-engineer-marvin` (adversarial QA execution), `technical-writer-trillian`, `Explore`/`general-purpose` (search), terminal/GUI/browser-automation verification.
   - **Haiku** — trivial mechanical (bulk search, formatting).
   Override per task both ways: downgrade a quality-critical agent for a trivial job; upgrade a routine agent for a genuinely hard one. **Security always escalates to Opus**: crypto, auth/key handling, network/transport, deserialization, untrusted input, dependency/version bumps, or a large/opaque diff. A passing vulnerability scan is NOT evidence of low risk; ALWAYS fully investigate a version bump, including the dependency's changed code. Cost breaks ties only among non-security work — when unsure, tier up. Sonnet 5 emits 1.0–1.35× more tokens than Sonnet 4.6 — still net cheaper, but watch cache-heavy sessions.
3. **Read discipline**: Grep/Glob first, Read with offset/limit. Delegate unavoidably large fetches to a disposable sonnet subagent that returns a summary (`git-and-github` § Context Management).
4. **Coordinator context**: the inline-vs-spawn axis is bounded-vs-bulk, not small-vs-large. Inline only BOUNDED work; when work would pull in bulk or unbounded data (large files, logs, wide searches), delegate to a disposable subagent so those bytes never enter the coordinator's context. For long sessions, summarise completed work to a task/file and rely on compaction rather than carrying full history.

## Scaling

**Splitting:** large tasks (50+ files) → multiple agents of the same type with different file scopes by package/module/layer.

**Batching:** merge small tasks so each agent gets roughly 300+ lines of work (soft target; a small follow-up to a live agent is still fine via `SendMessage`). Respect specialization boundaries — don't merge frontend with backend, security with docs, or unrelated domains; group by same layer, language, agent type.

## Scope

This skill owns the spawn decision: whether, how many, at which tier. Coordinator-only doctrine — session protocol, worktree mechanics, recovery, programme management — lives in `grand-admiral`. Any agent holding a Task tool can spawn, so this skill stands alone and assumes no `grand-admiral` load.
