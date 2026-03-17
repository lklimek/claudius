---
name: lessons-learned
description: "Extract and save learnings from conversation. Invoke before presenting plan, after notable events, and as final task when all work is complete."
---

# Lessons Learned

Extract, qualify, and persist reusable knowledge from the current session.

## Phase 1 — Gather

Scan the conversation for items worth remembering. Categories (see `${CLAUDE_SKILL_DIR}/../../references/source-of-truth.md` for the authoritative priority map):

- Architecture decisions & rationale
- Coding standards & conventions (not already in linters)
- Design patterns (error handling, module structure, etc.)
- Bad-thinking corrections (wrong approach -> corrected, e.g., returning String as error when typed errors are standard)
- Tool/environment quirks & workarounds
- User preferences
- Layer/module/file responsibilities

Collect as a numbered list. Search existing knowledge (`memcan:recall`) and drop duplicates.

### Quality Gate

Every candidate MUST pass ALL criteria before proceeding to Phase 2:

1. **Self-contained** — makes sense without conversation context
2. **Specific** — names the tool, library, pattern, or API
3. **Actionable** — a future session can use it directly
4. **Durable** — still matters in 30 days
5. **Not redundant** — not in source code, linter rules, or existing memories

**Good examples:**
- "Rust error handling: return typed errors via thiserror, never String — enables pattern matching"
- "Claude Code PreToolUse hooks receive agent_type as fully qualified plugin:agent name, not bare name — use prefix matching"

**Bad examples (do not save):**
- "All tests pass" (ephemeral)
- "File created: foo.rs" (process note)
- "Well-structured code" (vague)
- "Use git for version control" (well-known)

**Tone**: factual, third-person, present tense. Pattern: "[Subject]: [what/what to do] — [why/context]"

### Opportunistic Cleanup

During dedup searches, if existing memories fail the quality gate, update or delete them.

## Phase 2 — Save

For each qualified item:

1. **Assign scope**: global (cross-project, omit `project`) or project-scoped (set `project` to git remote origin repo name)
2. **Assign type**: lesson, decision, or preference
3. **Invoke `memcan:remember`** skill to persist each item
4. If memcan is unavailable, report findings but note they could not be persisted

Log each save: scope, type, one-line summary. Report total count.

**IMPORTANT**: This skill does NOT call memcan MCP tools directly. It invokes `memcan:remember` for saves and `memcan:recall` for searches. Claudius owns the classification logic; memcan is the execution layer.
