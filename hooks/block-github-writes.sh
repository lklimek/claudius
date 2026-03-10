#!/usr/bin/env bash
# Plugin-level PreToolUse hook: block GitHub MCP write tools for non-coordinator agents.
# Claudius (coordinator) and the main session retain full write access.
# Receives JSON on stdin with tool_name, agent_type (when in subagent).
set -euo pipefail

input=$(cat)
agent_type=$(echo "$input" | jq -r '.agent_type // ""')
tool_name=$(echo "$input" | jq -r '.tool_name // ""')

# Allow claudius and main session (no agent_type = main thread)
if [[ -z "$agent_type" || "$agent_type" == "claudius" ]]; then
  exit 0
fi

# Check if tool is a GitHub write operation
case "$tool_name" in
  mcp__plugin_claudius_github__actions_run_trigger|\
  mcp__plugin_claudius_github__add_comment_to_pending_review|\
  mcp__plugin_claudius_github__add_issue_comment|\
  mcp__plugin_claudius_github__add_reply_to_pull_request_comment|\
  mcp__plugin_claudius_github__create_branch|\
  mcp__plugin_claudius_github__create_or_update_file|\
  mcp__plugin_claudius_github__create_pull_request|\
  mcp__plugin_claudius_github__create_repository|\
  mcp__plugin_claudius_github__delete_file|\
  mcp__plugin_claudius_github__fork_repository|\
  mcp__plugin_claudius_github__issue_write|\
  mcp__plugin_claudius_github__merge_pull_request|\
  mcp__plugin_claudius_github__pull_request_review_write|\
  mcp__plugin_claudius_github__push_files|\
  mcp__plugin_claudius_github__sub_issue_write|\
  mcp__plugin_claudius_github__update_pull_request|\
  mcp__plugin_claudius_github__update_pull_request_branch)
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "GitHub write tools are blocked for subagents. Only the coordinator (claudius) has write access."
      }
    }'
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
