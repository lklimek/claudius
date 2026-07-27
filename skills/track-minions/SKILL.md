---
name: track-minions
description: "This skill should be used when tracking delegated or multi-step work in a durable store that survives context loss — before spawning agents, while a multi-task wave is in flight, and after compaction or other context loss to recover pending work. It applies to solo, delegated, and multi-agent work alike."
---

# Track Minions

An in-context checklist dies on compaction — exactly how multi-task work silently drops tasks. Track work in a durable store recoverable from scratch after any context loss.

## Primary — a plain file, in-session

Track in-flight work (agent dispatches, phases, file groups) in a plain file outside any git tree — not `/tmp` or anything else wipeable. Pick a stable path and simple format yourself; durability and recoverability are the point, not a fixed schema.

1. **Before starting**: write one entry per logical unit.
2. **While working**: update entries as they start/complete/block.
3. **After compaction or any context loss**: re-read the file to recover the in-flight list — never assume the in-context view is complete.

## Cross-session / cross-project — memcan todo

Use `memcan:todo` (`add_todo`/`list_todos`/`update_todo`/`complete_todo`) only for work that must survive a `/clear` or Claude Code restart, or that spans multiple projects (programme-management mode) — not for tracking a single session's in-flight work. Scope by `project` = repo short name from `git remote get-url origin`.

1. **Session start**: `list_todos(project=<repo>, status="pending")` to recover work left pending by a previous session.
2. Add/update/complete as that cross-session or cross-project work progresses.

## Scope

This skill owns tracking, not the spawn decision itself — see `claudius:delegate` for whether/how to spawn. The in-session file is the source of truth for work within a session; memcan todo is the source of truth across session boundaries and across projects.
