---
name: lessons-learned
description: "This skill should be used when extracting learnings, saving lessons, or capturing reusable knowledge from a session. It is also appropriate before presenting a plan, after notable events such as bugs or corrected approaches, and as the final task when work is complete."
---

# Lessons Learned

Extract, qualify, and persist reusable knowledge from the current session.

## Source of Truth

!`cat ${CLAUDE_SKILL_DIR}/../../references/source-of-truth.md`

## Phase 1 — Gather

Scan the conversation for items worth remembering, using the categories, quality gate, and examples from the Source of Truth above. Collect as a numbered list. Search existing knowledge (`memcan:recall`), drop duplicates, and apply the Source of Truth **Opportunistic Cleanup** to failing memories found during dedup.

**Tone**: factual, third-person, present tense. Pattern: "[Subject]: [what/what to do] — [why/context]". Apply the Source of Truth **Authoring rules**.

## Phase 2 — Save

For each qualified item:

1. **Assign scope**: global (cross-project, omit `project`) or project-scoped (`project` = git remote origin repo name)
2. **Assign type**: lesson, decision, or preference
3. **Invoke `memcan:remember`** to persist the item
4. If memcan is unavailable, report findings and note they were not persisted

Log each save: scope, type, one-line summary. Report total count.

**IMPORTANT**: never call memcan MCP tools directly — saves go through `memcan:remember`, searches through `memcan:recall`. Claudius owns classification; memcan executes.
