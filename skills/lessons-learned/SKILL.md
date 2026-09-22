---
name: lessons-learned
description: "This skill should be used when extracting learnings, saving lessons, or capturing reusable knowledge from a session. It is also appropriate before presenting a plan, after notable events such as bugs or corrected approaches, and as the final task when work is complete."
---

# Lessons Learned

Extract, qualify, and persist reusable knowledge from the current session.

## Source of Truth

!`cat ${CLAUDE_SKILL_DIR}/../../references/source-of-truth.md`

## Phase 1 — Gather

Scan the conversation for items passing the Source of Truth categories and quality gate; collect as a numbered list. `memcan:recall` to drop duplicates, applying **Opportunistic Cleanup** to failing memories found on the way. Phrase per the **Authoring rules**, factual and third-person: "[Subject]: [what/what to do] — [why/context]".

## Phase 2 — Save

For each qualified item:

1. **Scope**: global (omit `project`) or project-scoped (`project` = git remote origin repo name)
2. **Type**: lesson, decision, or preference
3. **`memcan:remember`** to persist; memcan unavailable → report the items and note they were not persisted

Log each save (scope, type, one-line summary) and the total. Never call memcan MCP tools directly for this skill's own save/dedup/search workflow — saves go through `memcan:remember`, searches through `memcan:recall`. (Exception: `grand-admiral`'s pre-delegation context injection calls the MCP `search` tool directly — that's a bulk lookup for prompt-briefing, not the classification/dedup work this skill owns.)
