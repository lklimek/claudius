#!/usr/bin/env bash
# Plugin-level PreToolUse hook: gate GitHub MCP tools for non-coordinator agents.
# Claudius (coordinator) and the main session retain full access; every other
# subagent is restricted to an explicit read-only ALLOWLIST — anything else that
# matches the mcp__plugin_claudius_github__ prefix is DENIED (default-deny).
#
# Fail-closed by design: if the policy cannot be evaluated (jq missing, stdin not
# a JSON object) the hook DENIES rather than letting the tool call proceed. A
# non-zero/non-2 exit would be treated as non-blocking by Claude Code and fail OPEN,
# so every rejection is emitted as an explicit permissionDecision:"deny" + exit 0.
#
# SCOPE BOUNDARY: this hook only covers the GitHub *MCP-tool* layer. A subagent with
# the Bash tool could still shell out to `gh` or `git push` — that path is out of
# reach here and is governed separately by each agent's per-agent Bash allowlist.
# The "subagents cannot write to GitHub" guarantee depends on BOTH controls.
set -euo pipefail

# Emit the fail-closed deny decision and exit 0 so Claude Code honors it. Uses printf
# (not jq) so it works even when jq is the thing that's missing. Reason strings are
# fixed ASCII literals with no JSON-special characters — safe to interpolate.
deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}

# jq is required to parse the payload; without it the policy cannot be evaluated.
command -v jq >/dev/null 2>&1 || \
  deny "GitHub tool blocked: jq unavailable, cannot evaluate access policy (fail-closed)."

input=$(cat)

# Reject anything that is not a JSON object (malformed, empty, or a bare scalar/array).
printf '%s' "$input" | jq -e 'type == "object"' >/dev/null 2>&1 || \
  deny "GitHub tool blocked: hook input was not a JSON object (fail-closed)."

agent_type=$(printf '%s' "$input" | jq -r '.agent_type // ""')
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // ""')

# Coordinator (claudius) and the main session (no agent_type) keep full access.
if [[ -z "$agent_type" || "$agent_type" == "claudius" || "$agent_type" == "claudius:claudius" ]]; then
  exit 0
fi

# Subagent: allow only known read-only GitHub tools; deny everything else. New or
# renamed write tools therefore default-deny instead of silently slipping through.
# Ordered by the toolsets enabled in .claude-plugin/.mcp.json (repos, issues,
# pull_requests, actions, code_security, secret_protection, dependabot,
# security_advisories) for auditability.
case "$tool_name" in
  mcp__plugin_claudius_github__get_file_contents|\
  mcp__plugin_claudius_github__get_commit|\
  mcp__plugin_claudius_github__list_commits|\
  mcp__plugin_claudius_github__list_branches|\
  mcp__plugin_claudius_github__list_tags|\
  mcp__plugin_claudius_github__get_latest_release|\
  mcp__plugin_claudius_github__get_release_by_tag|\
  mcp__plugin_claudius_github__list_releases|\
  mcp__plugin_claudius_github__search_code|\
  mcp__plugin_claudius_github__search_repositories|\
  mcp__plugin_claudius_github__issue_read|\
  mcp__plugin_claudius_github__list_issues|\
  mcp__plugin_claudius_github__list_issue_types|\
  mcp__plugin_claudius_github__search_issues|\
  mcp__plugin_claudius_github__get_label|\
  mcp__plugin_claudius_github__pull_request_read|\
  mcp__plugin_claudius_github__list_pull_requests|\
  mcp__plugin_claudius_github__search_pull_requests|\
  mcp__plugin_claudius_github__actions_get|\
  mcp__plugin_claudius_github__actions_list|\
  mcp__plugin_claudius_github__get_job_logs|\
  mcp__plugin_claudius_github__get_code_scanning_alert|\
  mcp__plugin_claudius_github__list_code_scanning_alerts|\
  mcp__plugin_claudius_github__get_secret_scanning_alert|\
  mcp__plugin_claudius_github__list_secret_scanning_alerts|\
  mcp__plugin_claudius_github__get_dependabot_alert|\
  mcp__plugin_claudius_github__list_dependabot_alerts|\
  mcp__plugin_claudius_github__get_global_security_advisory|\
  mcp__plugin_claudius_github__list_global_security_advisories|\
  mcp__plugin_claudius_github__list_org_repository_security_advisories|\
  mcp__plugin_claudius_github__list_repository_security_advisories)
    exit 0
    ;;
  *)
    deny "GitHub write tools are blocked for subagents. Only the coordinator (claudius) has write access."
    ;;
esac
