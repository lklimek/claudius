---
name: track-minions
description: "This skill should be used when tracking delegated or multi-step work in a durable store that survives context loss — before spawning agents, while a multi-task wave is in flight, and after compaction or other context loss to recover pending work. It applies to solo, delegated, and multi-agent work alike."
---

# Track Minions

An in-context checklist dies on compaction — exactly how multi-task work silently drops tasks. Track work in a durable store recoverable from scratch after any context loss.

## Primary — a plain file, in-session

Track in-flight work (agent dispatches, phases, file groups) in a plain file outside any git tree — not `/tmp` or anything wipeable. Any stable path and simple format; durability and recoverability are the point.

1. **Before starting**: one entry per logical unit.
2. **While working**: update entries as they start/complete/block.
3. **After compaction or any context loss**: re-read the file — never assume the in-context view is complete.

## Cross-session / cross-project — memcan todo

`memcan:todo` (`add_todo`/`list_todos`/`update_todo`/`complete_todo`) only for work that must survive a `/clear` or restart, or spans multiple projects (programme-management mode) — not a single session's in-flight work. Scope by `project` = repo short name from `git remote get-url origin`. At session start, `list_todos(project=<repo>, status="pending")` recovers work a previous session left pending.

## Scope

Tracking only — the spawn decision is `claudius:delegate`. The in-session file is the source of truth within a session; memcan todo across session and project boundaries.
