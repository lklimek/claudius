#!/usr/bin/env bash
# Agent-stall watchdog for multi-agent (grand-admiral) orchestration.
#
# Purpose
#   Fill the ONE gap the Claude Code harness does not cover: an agent that is
#   silently stuck but has NOT crashed. The harness already auto-notifies on
#   completion AND on death (crash / rate-limit / terminal error) with no
#   approval -- so this is NOT the primary death detector. It only flags
#   "alive but went quiet WITH WORK PENDING" so the coordinator can investigate.
#
# STALL == PENDING WORK + idle, NOT bare idle (key correctness property)
#   A team agent that finished its task and is waiting for the next message is
#   idle BY DESIGN -- flagging it is a false positive (the exact thing to avoid).
#   So a team agent is judged by its INBOX, not bare idle: an EMPTY inbox is
#   healthy and NEVER fires, no matter how long idle. Only an inbox that holds
#   UNPROCESSED messages that have sat untouched past the threshold stalls.
#
# ZERO MODEL TOKENS WHEN HEALTHY (hard contract)
#   This script is run by the `Monitor` tool, where every stdout LINE becomes a
#   coordinator notification that costs context tokens. It is therefore strictly
#   EDGE-TRIGGERED: it prints ONLY on an OK->STALL or STALL->RESUMED transition.
#   No per-poll output, no heartbeat, no "all clear", no debug on stdout (all
#   diagnostics go to stderr). Healthy operation == total stdout silence == zero
#   coordinator tokens. Tokens are spent only when a real stall fires.
#
# Monitor invocation (one persistent monitor per wave; autodetect by default):
#   Monitor(persistent=true, description="agent stall watchdog",
#           command="bash scripts/agent-watchdog.sh --stall-secs 300")
#
# CRITICAL -- a STALL line is a PRE-FILTER, never an auto-kill trigger
#   It is a prompt for the coordinator to INVESTIGATE (read the transcript,
#   `git -C <cwd> status/diff`, confirm no build), THEN decide. Restarting a
#   busy agent destroys in-flight work. Recovery doctrine: grand-admiral skill.
#
# Three agent sources (UNION; identical thresholds + build-suppression +
# no-epoch-skip + edge-triggered output applied to each; dedup by label,
# team-config entry wins)
#   SOURCE A -- TEAM agents (primary, pending-work model):
#     newest ~/.claude/teams/session-*/config.json -> members[] with
#     isActive==true AND agentType != "team-lead". Label = member `name`.
#     Signal = its inbox ~/.claude/teams/<dir>/inboxes/<name>.json:
#       empty == content "[]" (size <= 2 bytes); non-empty == work delivered,
#       not yet consumed. STALL when NON-EMPTY and inbox mtime age >= stall_secs
#       and not build_active (reason=inbox-unprocessed). RESUMED when a STALLED
#       agent's inbox drains to empty OR its mtime goes fresh (< resume_secs).
#       An empty inbox NEVER fires.
#   SOURCE B -- INDIVIDUAL / background subagents:
#     nested transcripts ~/.claude/projects/<slug>/<lead-uuid>/subagents/
#     agent-*.jsonl. Label = the `agent-<id>` filename stem. Signal = the
#     transcript's OWN mtime. STALL when idle >= stall_secs and not build_active
#     (reason=subagent-idle). Scoped to the CURRENT lead session: when a team
#     config is present its `leadSessionId` selects the exact subagents dir (so
#     a running team with no background subagents watches NONE, and stale
#     prior-session transcripts are never globbed); in pure individual mode
#     (no team config) it falls back to the subagents dir holding the newest
#     transcript. A transcript persists after an agent finishes, so a STALL
#     here is an INVESTIGATE prompt -- the harness already notified on a real
#     completion/crash.
#   SOURCE C -- WORKTREE-isolated agents:
#     .claude/worktrees/agent-* dirs. Label = dir name. Signal = newest mtime
#     under the dir. STALL when idle >= stall_secs and not build_active
#     (reason=worktree-idle).
#
# Cross-checks (all sources)
#   * build_active: a single global `pgrep` (cargo|rustc|go|node|pytest|tsc|
#     npm|pnpm|yarn) suppresses STALL for ALL agents this poll. A HEALTHY agent
#     blocked on one long cold build (10-20 min) writes nothing, so any running
#     build conservatively suppresses STALL. A false "OK" is cheap (re-checked
#     next poll); a false STALL that kills a building agent is not.
#   * NO epoch fallback: if a signal is missing this poll, SKIP the agent --
#     never default mtime to 0 (which computes idle vs 1970 -> ~56-year STALLs).
#
# Args (all optional; sane defaults shown)
#   --team-dir     DIR  team session dir w/ config.json + inboxes/
#                       (default: newest ~/.claude/teams/session-*)
#   --projects-dir DIR  projects base searched for <slug>/<uuid>/subagents/
#                       (default: ~/.claude/projects)
#   --worktrees    DIR  worktree root holding agent-* dirs
#                       (default: .claude/worktrees)
#   --stall-secs   N    idle/age seconds before STALL              (default: 300)
#   --resume-secs  N    idle/age seconds below which a STALLED      (default: 60)
#                       agent is declared RESUMED
#   --poll-secs    N    seconds between polls                       (default: 45)
#
# (Optional ~/.claude/sessions/<pid>.json `status`/`waitingFor` annotation was
# evaluated and intentionally SKIPPED: those files key on pid/sessionId/job-name
# with no cheap, reliable mapping to a team member name, and `waitingFor` is not
# consistently present -- folding it in would complicate the core for little
# gain.)
#
# Output (ONLY these two line shapes ever reach stdout)
#   STALL agent=<key> idle=<N>s reason=<inbox-unprocessed|subagent-idle|worktree-idle>
#   RESUMED agent=<key> idle=<N>s
#
# Exit: runs forever; transient stat/find/pgrep/python3 failures are swallowed
# (|| true) so a momentary filesystem hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
team_dir=""
projects_dir="$HOME/.claude/projects"
worktrees_dir=".claude/worktrees"
stall_secs=300
resume_secs=60
poll_secs=45

# ---- helpers --------------------------------------------------------------
die() { printf 'agent-watchdog: %s\n' "$1" >&2; exit 1; }
require_int() { [[ "$2" =~ ^[0-9]+$ ]] || die "$1 expects a non-negative integer, got: $2"; }

usage() {
  cat >&2 <<'USAGE'
agent-watchdog.sh -- edge-triggered agent-stall watchdog (silent when healthy)
Usage: agent-watchdog.sh [--team-dir DIR] [--projects-dir DIR] [--worktrees DIR]
                         [--stall-secs N] [--resume-secs N] [--poll-secs N]
Defaults: team-dir=newest ~/.claude/teams/session-*  projects-dir=~/.claude/projects
          worktrees=.claude/worktrees  stall=300 resume=60 poll=45
STALL = pending work + idle (team agents judged by inbox, empty=healthy).
Emits ONLY 'STALL'/'RESUMED' transition lines to stdout; diagnostics to stderr.
USAGE
}

newest_path_in() {
  # Echo the newest-by-mtime entry under $1 matching the remaining find args.
  local dir="$1"; shift
  [ -d "$dir" ] || return 0
  find "$dir" "$@" -printf '%T@\t%p\n' 2>/dev/null | sort -rn | head -n1 | cut -f2- || true
}

newest_mtime_under() {
  # Echo the max integer epoch mtime of ANY entry under $1, or nothing.
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -printf '%T@\n' 2>/dev/null | sort -rn | head -n1 || true)"
  printf '%s' "${m%.*}"
}

file_mtime() { [ -e "$1" ] || return 0; stat -c %Y "$1" 2>/dev/null || true; }

parse_team() {
  # Emit "LEAD<TAB><sessionId>" and one "MEMBER<TAB><name>" per watchable member
  # (isActive==true, not the team-lead). $1 = config.json path.
  python3 - "$1" <<'PY' 2>/dev/null || true
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
print("LEAD\t" + (c.get("leadSessionId") or ""))
for m in c.get("members", []):
    if m.get("isActive") is True and m.get("agentType") != "team-lead":
        n = m.get("name") or ""
        if n:
            print("MEMBER\t" + n)
PY
}

declare -A STATE   # key -> OK | STALLED  (survives across polls)

evaluate_mtime() {
  # mtime-based sources (B, C). $1=key $2=reason $3=activity-epoch.
  local key="$1" reason="$2" act_e="$3" idle state
  [[ "$act_e" =~ ^[0-9]+$ ]] || return 0          # no signal -> SKIP (no epoch-0)
  idle=$(( now - act_e ))
  state="${STATE[$key]:-OK}"
  if [ "$idle" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$state" != "STALLED" ]; then
    STATE["$key"]="STALLED"
    printf 'STALL agent=%s idle=%ss reason=%s\n' "$key" "$idle" "$reason"
  elif [ "$state" = "STALLED" ] && [ "$idle" -lt "$resume_secs" ]; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
  fi
}

evaluate_team() {
  # Pending-work model. $1=key $2=inbox path. Empty inbox is healthy (no fire).
  local key="$1" inbox="$2" size mt age state
  size="$(stat -c %s "$inbox" 2>/dev/null || true)"
  [[ "$size" =~ ^[0-9]+$ ]] || return 0           # inbox missing -> no signal
  mt="$(stat -c %Y "$inbox" 2>/dev/null || true)"
  [[ "$mt" =~ ^[0-9]+$ ]] || return 0
  age=$(( now - mt ))
  state="${STATE[$key]:-OK}"
  if [ "$size" -gt 2 ] && [ "$age" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$state" != "STALLED" ]; then
    STATE["$key"]="STALLED"
    printf 'STALL agent=%s idle=%ss reason=inbox-unprocessed\n' "$key" "$age"
  elif [ "$state" = "STALLED" ] && { [ "$size" -le 2 ] || [ "$age" -lt "$resume_secs" ]; }; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$age"
  fi
}

# ---- arg parsing ----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --team-dir)     [ $# -ge 2 ] || die "--team-dir needs a value";     team_dir="$2";     shift 2 ;;
    --projects-dir) [ $# -ge 2 ] || die "--projects-dir needs a value"; projects_dir="$2"; shift 2 ;;
    --worktrees)    [ $# -ge 2 ] || die "--worktrees needs a value";    worktrees_dir="$2"; shift 2 ;;
    --stall-secs)   [ $# -ge 2 ] || die "--stall-secs needs a value";   require_int "$1" "$2"; stall_secs="$2";  shift 2 ;;
    --resume-secs)  [ $# -ge 2 ] || die "--resume-secs needs a value";  require_int "$1" "$2"; resume_secs="$2"; shift 2 ;;
    --poll-secs)    [ $# -ge 2 ] || die "--poll-secs needs a value";    require_int "$1" "$2"; poll_secs="$2";   shift 2 ;;
    -h|--help)      usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ "$poll_secs" -ge 1 ] || die "--poll-secs must be >= 1"

have_py=0
if command -v python3 >/dev/null 2>&1; then have_py=1; fi
[ "$have_py" -eq 1 ] || printf 'agent-watchdog: python3 not found; team source disabled, subagents/worktrees only\n' >&2

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss team-dir=%s projects-dir=%s worktrees=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "${team_dir:-<auto>}" "$projects_dir" "$worktrees_dir" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    sleep "$poll_secs" || true          # clock read failed -- skip, don't guess
    continue
  fi

  td="$team_dir"; [ -n "$td" ] || td="$(newest_path_in "$HOME/.claude/teams" -maxdepth 1 -type d -name 'session-*')"

  unset SEEN; declare -A SEEN

  # global, best-effort: any build suppresses STALL for every agent this poll.
  build_active=0
  if pgrep -f 'cargo|rustc|go build|go test|node |pytest|jest|tsc|webpack|npm |pnpm |yarn ' >/dev/null 2>&1; then
    build_active=1
  fi

  # ---- SOURCE A: team members (pending-work) ----
  team_present=0; lead_session=""; team_members=()
  if [ "$have_py" -eq 1 ] && [ -n "$td" ] && [ -f "$td/config.json" ]; then
    team_present=1
    while IFS=$'\t' read -r kind val; do
      case "$kind" in
        LEAD)   lead_session="$val" ;;
        MEMBER) [ -n "$val" ] && team_members+=("$val") ;;
      esac
    done < <(parse_team "$td/config.json")
    for name in "${team_members[@]:-}"; do
      [ -n "$name" ] || continue
      [ -n "${SEEN[$name]:-}" ] && continue
      SEEN["$name"]=1
      evaluate_team "$name" "$td/inboxes/$name.json"
    done
  fi

  # ---- SOURCE B: individual / background subagent transcripts ----
  sub_dir=""
  if [ "$team_present" -eq 1 ]; then
    # team present -> watch ONLY the current lead session's subagents (if any);
    # never fall back to stale prior-session dirs.
    [ -n "$lead_session" ] && sub_dir="$(find "$projects_dir" -maxdepth 3 -type d -path "*/$lead_session/subagents" 2>/dev/null | head -n1 || true)"
  else
    # pure individual mode -> the subagents dir holding the newest transcript.
    sub_dir="$(find "$projects_dir" -maxdepth 4 -type f -path '*/subagents/agent-*.jsonl' -printf '%T@\t%h\n' 2>/dev/null | sort -rn | head -n1 | cut -f2- || true)"
  fi
  if [ -n "$sub_dir" ] && [ -d "$sub_dir" ]; then
    for f in "$sub_dir"/agent-*.jsonl; do
      [ -e "$f" ] || continue
      base="${f##*/}"; key="${base%.jsonl}"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      evaluate_mtime "$key" "subagent-idle" "$(file_mtime "$f")"
    done
  fi

  # ---- SOURCE C: worktree-isolated agents ----
  if [ -n "$worktrees_dir" ] && [ -d "$worktrees_dir" ]; then
    for d in "$worktrees_dir"/agent-*; do
      [ -d "$d" ] || continue
      key="${d##*/}"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      evaluate_mtime "$key" "worktree-idle" "$(newest_mtime_under "$d")"
    done
  fi

  sleep "$poll_secs" || true
done
