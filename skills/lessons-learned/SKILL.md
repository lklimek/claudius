---
name: lessons-learned
description: "Use when extracting learnings, saving lessons, or capturing reusable knowledge from the session. Also appropriate before presenting a plan, after notable events (bugs, wrong approaches corrected), and as final task when work is complete."
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

Every candidate MUST pass the quality gate in `${CLAUDE_SKILL_DIR}/../../references/source-of-truth.md`. Reject anything that fails any criterion.

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
