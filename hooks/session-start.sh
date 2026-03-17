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
  systemMessage: ("## Knowledge Source Priorities\n\n" + $sot + "\n\nIf persistent memory tools are available (memcan), search for project context using the categories above. Use `memcan:recall` skill. If memcan is unavailable, skip silently.")
}'
