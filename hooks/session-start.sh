#!/usr/bin/env bash
# Plugin-level SessionStart hook: inject persistent memory search reminder.
# SessionStart only supports command hooks (not prompt hooks).
set -euo pipefail

# Resolve source-of-truth path relative to plugin root
SOT="${CLAUDE_PLUGIN_ROOT}/references/source-of-truth.md"

jq -n --arg sot "$SOT" '{
  systemMessage: ("Read `" + $sot + "` for knowledge source priorities. Then, if persistent memory tools are available (memcan), search for project context using categories from that file. Use `memcan:recall` skill. If memcan is unavailable, skip silently.")
}'
exit 0
