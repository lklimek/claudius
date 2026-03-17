#!/usr/bin/env bash
# Plugin-level SessionStart hook: inject persistent memory search reminder.
# SessionStart only supports command hooks (not prompt hooks).
set -euo pipefail

# Inline source-of-truth content into system message
SOT="${CLAUDE_PLUGIN_ROOT}/references/source-of-truth.md"
SOT_CONTENT=""
if [[ -f "$SOT" ]]; then
  SOT_CONTENT=$(cat "$SOT")
fi

jq -n --arg sot "$SOT_CONTENT" '{
  systemMessage: ("## Knowledge Source Priorities\n\n" + $sot + "\n\n## Memory Actions\n\n**On session start**: If persistent memory tools are available (memcan), search for project context using the categories above. Use `memcan:recall` skill. If memcan is unavailable, skip silently.\n\n**Invoke `claudius:lessons-learned`** when any of these occur:\n- Architecture decision made or changed\n- Coding standard established or clarified\n- Wrong approach corrected (bad-thinking pattern)\n- Non-obvious tool/environment quirk discovered\n- User states a preference or convention\n- Plan changes direction\n- Session ends with new knowledge worth preserving\n\nDo NOT invoke for routine work with no new decisions or corrections.")
}'
