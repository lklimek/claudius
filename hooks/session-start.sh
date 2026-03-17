#!/usr/bin/env bash
# Plugin-level SessionStart hook: inject persistent memory search reminder.
# SessionStart only supports command hooks (not prompt hooks).
set -euo pipefail

jq -n '{
  systemMessage: "If persistent memory tools are available (memcan), search for project context: architecture decisions, coding conventions, known pitfalls, pending TODOs. Use `memcan:recall` skill. If memcan is unavailable, skip silently."
}'
exit 0
