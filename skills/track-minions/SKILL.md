---
name: track-minions
description: "Use to track delegated and multi-step work in a durable store that survives context loss — before spawning agents, while a multi-task wave is in flight, and after compaction or any context loss to recover pending work. Applies to solo, delegated, and multi-agent work alike."
---

# Track Minions

An in-context checklist is not enough — it dies on compaction, which is exactly how multi-task work silently drops tasks. Track work in a durable store recoverable from scratch after any context loss.

## Primary — memcan TODOs

`memcan:todo` (tools `add_todo`/`list_todos`/`update_todo`/`complete_todo`). Scope by `project` = the repo short name from `git remote get-url origin`, so the list is recoverable with nothing to remember.

1. **Session start / after compaction**: `list_todos(project=<repo>, status="pending")` to recover in-flight work — never assume the in-context list is complete.
2. **Before starting**: `add_todo` one item per logical unit (agent dispatch, phase, file group).
3. **While working**: `complete_todo` when done, `update_todo` otherwise — the tool's `status` accepts `pending`/`done`/`in_progress`/`blocked`/`postponed`/`cancelled` directly; set `owner` for the responsible agent and `priority` for ordering.
4. **Between steps**: re-list to decide the next action and catch forgotten work.

## Fallback — a plain durable file

Only when memcan tools are unavailable (e.g. headless/cron). Keep the same list in a file outside any git tree; choose a stable, deterministic location and simple format yourself and re-read it after context loss — durability and recoverability are the point, not a fixed schema.

## Scope

This skill owns tracking, not the spawn decision itself — see `claudius:delegate` for whether/how to spawn. The durable store is the source of truth for outstanding work; an in-context list is a cache of it at best.
