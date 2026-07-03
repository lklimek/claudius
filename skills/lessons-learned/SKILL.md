---
name: lessons-learned
description: "Use when extracting learnings, saving lessons, or capturing reusable knowledge from the session. Also appropriate before presenting a plan, after notable events (bugs, wrong approaches corrected), and as final task when work is complete."
---

# Lessons Learned

Extract, qualify, and persist reusable knowledge from the current session.

## Source of Truth

!`cat ${CLAUDE_SKILL_DIR}/../../references/source-of-truth.md`

## Phase 1 — Gather

Scan the conversation for items worth remembering. Use the categories, quality gate, and examples from the Source of Truth above.

Collect as a numbered list. Search existing knowledge (`memcan:recall`) and drop duplicates.

**Tone**: factual, third-person, present tense. Pattern: "[Subject]: [what/what to do] — [why/context]". Apply the Source of Truth **Authoring rules** — self-contained phrasing (no pronouns/anaphora; inline the subject) and timeless present tense (strip "now"/"previously"/"currently"/"no longer").

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
