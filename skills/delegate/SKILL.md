---
name: delegate
description: "Use before delegating any task to an agent — a single Agent() spawn or a whole wave — and whenever the user says \"spawn an agent\", \"delegate this\", \"parallelize this\", \"split this work\", or \"use a subagent\". Also applies when choosing a model tier, batching small tasks, or deciding inline-vs-spawn. Reload before every delegation, not once per session."
---

# Delegate

Run before every `Agent()` call — cheap enough to reload each time. Spawning is the dominant token cost: every subagent rebuilds its context cache from scratch, and cache-creation, not model output, is the bulk of the bill. The cheapest work is the spawn that never happens.

## Pre-Delegation Checklist

1. **Total scope size** — sum the estimated diff/output across the whole batch, not per item. Under ~100 lines total: fold into an existing or sibling agent via `SendMessage`; do not spawn.
2. **Genuine parallelism** — is there a real wall-clock or file-independence need, or would sequential work merely take "a bit longer"? No real need → one agent, sequential.
3. **Reuse** — is an agent already live in the same file/domain scope? → `SendMessage` it. Accumulated context beats a cold spawn (see § Agent Reuse in `grand-admiral`).
4. **Model tier** — set explicitly on this spawn per the table below. Never leave it to the agent's frontmatter fallback.
5. **Worktree** — for code-mutating agents: pre-create it and inject the resolved SHA. Never rely on `isolation: "worktree"` alone (see § Worktree Isolation in `grand-admiral`).
6. **Monitoring** — is a watchdog running for this session (MCP preferred, else the built-in Monitor)? An un-monitored dispatch is a doctrine violation (see § Recovery in `grand-admiral`).
7. **Development work?** — brief the goal only, no file list/approach; the agent plans and the coordinator approves (see `grand-admiral` § Development-Work Delegation).

**Anti-pattern — file-independence is not spawn-justification.** Real case: four doc-only fixes, each under 20 lines in its own file, got four separate Opus spawns — the batch totalled well under 100 lines and belonged to one agent. Independent files justify a separate worktree or commit, NOT automatically a separate agent.

## Token Economy

Four mandatory rules:

1. **Spawn discipline**: default to inline for small/sequential work in the warm parent context. Spawn ONLY for genuinely parallel independent work, large scope (~20k+ output tokens, or many files), or required context isolation.
2. **Model tiering (mandatory)**: set model on every spawn — the agent's frontmatter `model:` is only the fallback when you don't. **Sonnet 5** (`sonnet` alias auto-resolves to it) is the capable default workhorse: ~91% of Opus on SWE-bench Pro, best-in-class terminal/computer-use, strong self-verification, native 1M context, ~1.67× cheaper than Opus (2.5× cheaper until 2026-08-31). Tier per agent by where quality is load-bearing:
   - **Opus** — quality-critical reasoning / agentic depth: `developer-bilby` (agentic coding), `project-reviewer-adams` (project consistency + structural/idiom code-quality review), `architect-nagatha` (system design, dependency/tech trade-offs, plan validation), `ux-designer-diziet` (UX), `security-engineer-smythe` (security / high-risk). These carry `model: opus` as their frontmatter fallback.
   - **Sonnet 5** — agentic-but-routine: the coordinator, `qa-engineer-marvin` (adversarial QA execution — tests, lints, edge cases, independent verification against ground truth), `technical-writer-trillian` (docs), `Explore` / `general-purpose` (search), and terminal / GUI / browser-automation verification (Sonnet 5 leads OSWorld / Terminal-bench).
   - **Haiku** — trivial mechanical (bulk search, formatting).
   Override per task, both ways: downgrade a quality-critical agent to Sonnet 5 for a trivial job; upgrade a routine agent to Opus for a genuinely hard one. **Risk-based tiebreaker — security always escalates to Opus**: every security-sensitive task goes to Opus regardless of its generic tier — crypto, auth/key handling, network/transport, deserialization, untrusted input, dependency/version bumps, or a large/opaque diff. A passing vulnerability scan (e.g. govulncheck) is NOT evidence of low risk and never justifies a downgrade; ALWAYS fully investigate a version bump, including verifying the updated dependency's changed code. Cost breaks ties only among non-security work — when unsure, tier up. **Tokenizer caveat**: Sonnet 5 emits 1.0–1.35× more tokens than Sonnet 4.6 — still net cheaper, but watch cache-heavy sessions.
3. **Read discipline**: prefer Grep/Glob first and Read with offset/limit. Delegate unavoidably large fetches to a disposable sonnet subagent that returns a summary — see `git-and-github` § Context Management.
4. **Coordinator context**: inlining keeps work in the coordinator's own context, which grows with it — so the axis is bounded-vs-bulk, not small-vs-large. Inline only BOUNDED work; when work would pull in bulk or unbounded data (large files, logs, wide searches), delegate to a disposable subagent so those bytes never enter the coordinator's context (the spawn cost buys context hygiene). For long sessions, summarise completed work to a task/file and rely on context compaction rather than carrying full history.

## Scaling

**Splitting:** For large tasks (50+ files), spawn multiple agents of same type with different file scopes split by package/module/layer.

**Batching:** Merge small tasks so each agent gets >=100 lines of work. Avoid spawning agents for tiny isolated changes. Respect specialization boundaries — don't merge frontend with backend, security with docs, or unrelated domains. Group by: same layer, same language, same agent type.

## Scope

This skill owns the spawn decision: whether to spawn, how many, and at which tier. Coordinator-only doctrine — session protocol, worktree mechanics, recovery, programme management — lives in `grand-admiral`. Any agent holding a Task tool can spawn, so this skill stands alone and assumes no `grand-admiral` load.
