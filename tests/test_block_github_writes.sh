#!/usr/bin/env bash
# Unit test: block-github-writes.sh PreToolUse gate must FAIL CLOSED.
#
# Proves the two independently-confirmed fail-open modes are fixed and
# that the coordinator/read-only paths still work:
#   C1  malformed (non-JSON) stdin        -> DENY (no crash, no allow)
#   C2  empty stdin                        -> DENY
#   C3  valid JSON but not an object       -> DENY
#   C4  subagent + read-only tool          -> ALLOW  (don't break legit reads)
#   C5  subagent + another read-only tool  -> ALLOW
#   C6  subagent + dependabot write        -> DENY   (previously-uncovered gap)
#   C7  subagent + code_security write     -> DENY   (previously-uncovered gap)
#   C8  subagent + secret_protection write -> DENY   (previously-uncovered gap)
#   C9  subagent + security_advisories wr. -> DENY   (previously-uncovered gap)
#   C10 subagent + unknown future tool     -> DENY   (default-deny posture)
#   C11 subagent + classic write (merge)   -> DENY   (regression guard)
#   C12 subagent + add_issue_comment       -> DENY   (regression guard)
#   C13 coordinator (claudius) + write     -> ALLOW  (coordinator keeps write)
#   C14 main session (no agent_type) + wr. -> ALLOW  (main keeps write)
#   C15 jq missing from PATH + valid JSON  -> DENY   (no crash-to-allow)
#   C16 subagent + empty tool_name         -> DENY   (defensive)
#   C17 subagent + get_me (context read)   -> ALLOW  (enabled context toolset in allowlist)
#
# Fully isolated: no repo state touched, all input on stdin.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="${HOOK:-$SCRIPT_DIR/../hooks/block-github-writes.sh}"
BASHBIN="$(command -v bash)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

# Run the hook with the given stdin. Optional 2nd arg overrides PATH for the hook
# process (used to simulate a missing jq). Sets globals OUT (stdout) and RC (exit).
run_hook() {
  local stdin="$1" pathval="${2-}"
  if [ -n "$pathval" ]; then
    OUT=$(printf '%s' "$stdin" | env PATH="$pathval" "$BASHBIN" "$HOOK" 2>/dev/null); RC=$?
  else
    OUT=$(printf '%s' "$stdin" | "$BASHBIN" "$HOOK" 2>/dev/null); RC=$?
  fi
}

is_deny() { grep -Eq '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"' <<<"$OUT"; }

# Assert the hook DENIED: emitted a deny decision and exited 0 (honored, not crashed).
assert_deny() {  # $1=desc $2=stdin $3=optional-PATH
  run_hook "$2" "${3-}"
  if is_deny && [ "$RC" -eq 0 ]; then
    ok "$1"
  else
    bad "$1 (rc=$RC out='${OUT//$'\n'/ }')"
  fi
}

# Assert the hook ALLOWED: emitted no deny decision and exited 0.
assert_allow() {  # $1=desc $2=stdin
  run_hook "$2"
  if ! is_deny && [ "$RC" -eq 0 ]; then
    ok "$1"
  else
    bad "$1 (rc=$RC out='${OUT//$'\n'/ }')"
  fi
}

P='mcp__plugin_claudius_github__'
sub() {  # build subagent hook payload: $1=tool_name
  printf '{"agent_type":"claudius:security-engineer","tool_name":"%s"}' "$1"
}

echo "=== fail-closed on bad input (fail-open mode 2) ==="
assert_deny "C1 malformed non-JSON stdin denies (no crash)" 'not json at all'
assert_deny "C2 empty stdin denies"                          ''
assert_deny "C3 valid JSON but not an object denies"         '[1,2,3]'
echo ""

echo "=== read-only tools still allowed for subagents ==="
assert_allow "C4 subagent + pull_request_read allowed"  "$(sub "${P}pull_request_read")"
assert_allow "C5 subagent + get_file_contents allowed"  "$(sub "${P}get_file_contents")"
echo ""

echo "=== default-deny closes the enabled-but-unlisted write toolsets (fail-open mode 1) ==="
assert_deny "C6 subagent + dependabot write denied"          "$(sub "${P}update_dependabot_alert")"
assert_deny "C7 subagent + code_security write denied"       "$(sub "${P}update_code_scanning_alert")"
assert_deny "C8 subagent + secret_protection write denied"   "$(sub "${P}update_secret_scanning_alert")"
assert_deny "C9 subagent + security_advisories write denied" "$(sub "${P}create_repository_security_advisory")"
assert_deny "C10 subagent + unknown future tool denied"      "$(sub "${P}some_future_write_tool")"
echo ""

echo "=== regression: classic writes still denied ==="
assert_deny "C11 subagent + merge_pull_request denied" "$(sub "${P}merge_pull_request")"
assert_deny "C12 subagent + add_issue_comment denied"  "$(sub "${P}add_issue_comment")"
echo ""

echo "=== coordinator + main session retain full write access ==="
assert_allow "C13 coordinator (claudius) + merge_pull_request allowed" \
  "$(printf '{"agent_type":"claudius","tool_name":"%smerge_pull_request"}' "$P")"
assert_allow "C14 main session (no agent_type) + merge_pull_request allowed" \
  "$(printf '{"tool_name":"%smerge_pull_request"}' "$P")"
echo ""

echo "=== missing jq must deny, not crash-to-allow ==="
FAKEBIN="$(mktemp -d)"
trap 'rm -rf "$FAKEBIN"' EXIT
ln -s "$(command -v cat)" "$FAKEBIN/cat" 2>/dev/null || true
assert_deny "C15 jq absent from PATH denies (no crash)" \
  "$(sub "${P}pull_request_read")" "$FAKEBIN"
echo ""

echo "=== defensive: empty tool_name for a subagent ==="
assert_deny "C16 subagent + empty tool_name denied" '{"agent_type":"claudius:x","tool_name":""}'
echo ""

echo "=== enabled context toolset read tool must be allowlisted ==="
assert_allow "C17 subagent + get_me (context read) allowed" "$(sub "${P}get_me")"
echo ""

echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
