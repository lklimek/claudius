#!/usr/bin/env bash
# Agent-stall watchdog for multi-agent (grand-admiral) orchestration.
#
# Purpose
#   Fill the ONE gap the Claude Code harness does not cover: an agent that is
#   silently stuck but has NOT crashed. The harness already auto-notifies on
#   completion AND on death (crash / rate-limit / terminal error) with no
#   approval -- so this is NOT the primary death detector. It only flags an
#   agent that OWNS ASSIGNED WORK yet has gone quiet, so the coordinator can
#   investigate.
#
# STALL == OWNS AN IN-PROGRESS TASK + idle, NOT bare idle (key correctness rule)
#   Bare idle is not a stall: a healthy team agent idles while waiting for its
#   next instruction, and flagging that is the exact false positive to avoid.
#   A NAMED agent (team member / worktree) is judged stalled only when it OWNS
#   an in_progress task AND has been idle past the threshold AND no build runs.
#   "Owns work" is read from the on-disk task store (the source of truth), not
#   guessed. An idle agent with no in_progress task is healthy and NEVER fires.
#   ANONYMOUS background subagents are NOT gated (they run one task to
#   completion and don't idle-wait; the harness notifies on their completion).
#
# ZERO MODEL TOKENS WHEN HEALTHY (hard contract)
#   This script is run by the `Monitor` tool, where every stdout LINE becomes a
#   coordinator notification that costs context tokens. It is therefore strictly
#   EDGE-TRIGGERED: it prints ONLY on an OK->STALL or STALL->RESUMED transition.
#   No per-poll output, no heartbeat, no "all clear", no debug on stdout (all
#   diagnostics go to stderr). Healthy operation == total stdout silence == zero
#   coordinator tokens.
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
# Task store (the ownership gate)
#   Tasks live at ~/.claude/tasks/<teamName>/<id>.json, where <teamName> is the
#   `name` field of the team config.json (same trailing name as the team dir,
#   e.g. "session-f393f3c9"). Each file has `owner` (agent name) and `status`
#   (pending|in_progress|completed). Each poll a set OWNERS_WITH_WORK =
#   { owner : status=="in_progress" } is rebuilt and gates the NAMED sources.
#   If the task store is missing/empty, no NAMED agent is ever flagged (fail
#   safe: under-alert rather than false-alert).
#
# Three discovery sources (UNION; build-suppression + no-epoch-skip + strictly
# edge-triggered output apply to all; dedup by label, team entry wins)
#   SOURCE A -- TEAM agents (NAMED, gated): newest
#     ~/.claude/teams/session-*/config.json members with isActive==true AND
#     agentType != "team-lead". Label = member `name`. Activity clock = newest
#     mtime under the member's worktree (.claude/worktrees/agent-<name>) if it
#     exists, else newest mtime under its `cwd`. STALL only if idle >= stall_secs
#     AND not build_active AND the label OWNS an in_progress task
#     (-> task-owned=in_progress).
#   SOURCE B -- INDIVIDUAL / background subagents (ANONYMOUS, NOT gated):
#     ~/.claude/projects/<slug>/<leadSessionId>/subagents/agent-*.jsonl. Label =
#     the agent-<id> filename stem. Activity = the transcript's own mtime. STALL
#     if idle >= stall_secs AND not build_active (-> reason=subagent-idle).
#     Scoped to the current lead session (team's leadSessionId) so finished
#     prior-session transcripts are never flagged; pure-individual mode falls
#     back to the subagents dir holding the newest transcript.
#   SOURCE C -- WORKTREE-isolated agents (NAMED, gated): .claude/worktrees/
#     agent-* dirs. Label = dir name. Activity = newest mtime under the dir.
#     Same task-ownership gate as Source A (owner matched on the label and on
#     the label with its leading "agent-" stripped).
#
# Cross-checks (all sources)
#   * build_active: a single global `pgrep` (cargo|rustc|go|node|pytest|tsc|
#     npm|pnpm|yarn) suppresses STALL for ALL agents this poll. A HEALTHY agent
#     blocked on one long cold build writes nothing; any running build
#     conservatively suppresses STALL. A false "OK" is cheap; a false STALL that
#     kills a building agent is not.
#   * NO epoch fallback: if a signal is missing this poll, SKIP the agent --
#     never default mtime to 0 (which computes idle vs 1970 -> ~56-year STALLs).
#
# Args (all optional; sane defaults shown)
#   --team-dir     DIR  team session dir w/ config.json
#                       (default: newest ~/.claude/teams/session-*)
#   --tasks-dir    DIR  task store dir (default: ~/.claude/tasks/<teamName>
#                       from config.json name; fallback newest
#                       ~/.claude/tasks/session-*)
#   --projects-dir DIR  projects base searched for <slug>/<uuid>/subagents/
#                       (default: ~/.claude/projects)
#   --worktrees    DIR  worktree root holding agent-* dirs
#                       (default: .claude/worktrees)
#   --stall-secs   N    idle seconds before STALL                  (default: 300)
#   --resume-secs  N    idle seconds below which a STALLED agent    (default: 60)
#                       is declared RESUMED
#   --poll-secs    N    seconds between polls                       (default: 45)
#
# Output (ONLY these line shapes ever reach stdout)
#   STALL agent=<name> idle=<N>s task-owned=in_progress     (named: A, C)
#   STALL agent=<key>  idle=<N>s reason=subagent-idle       (anonymous: B)
#   RESUMED agent=<key> idle=<N>s
#
# Exit: runs forever; transient stat/find/pgrep/python3 failures are swallowed
# (|| true) so a momentary filesystem hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
team_dir=""
tasks_dir=""
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
Usage: agent-watchdog.sh [--team-dir DIR] [--tasks-dir DIR] [--projects-dir DIR]
                         [--worktrees DIR] [--stall-secs N] [--resume-secs N] [--poll-secs N]
STALL = owns an in_progress task AND idle past threshold AND no build running.
An idle agent with no assigned in_progress task is healthy and never flagged.
Emits ONLY 'STALL'/'RESUMED' transition lines to stdout; diagnostics to stderr.
USAGE
}

newest_path_in() {
  local dir="$1"; shift
  [ -d "$dir" ] || return 0
  find "$dir" "$@" -printf '%T@\t%p\n' 2>/dev/null | sort -rn | head -n1 | cut -f2- || true
}

newest_mtime_under() {
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -printf '%T@\n' 2>/dev/null | sort -rn | head -n1 || true)"
  printf '%s' "${m%.*}"
}

file_mtime() { [ -e "$1" ] || return 0; stat -c %Y "$1" 2>/dev/null || true; }

parse_team() {
  # Emit "NAME<TAB><teamName>", "LEAD<TAB><sessionId>", and one
  # "MEMBER<TAB><name><TAB><cwd>" per watchable member (isActive, not lead).
  python3 - "$1" <<'PY' 2>/dev/null || true
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
print("NAME\t" + (c.get("name") or ""))
print("LEAD\t" + (c.get("leadSessionId") or ""))
for m in c.get("members", []):
    if m.get("isActive") is True and m.get("agentType") != "team-lead":
        n = m.get("name") or ""
        if n:
            print("MEMBER\t" + n + "\t" + (m.get("cwd") or ""))
PY
}

build_owners() {
  # Print one owner per line for tasks whose status == in_progress. $1 = dir.
  python3 - "$1" <<'PY' 2>/dev/null || true
import json, sys, glob, os
d = sys.argv[1]
if not d or not os.path.isdir(d):
    sys.exit(0)
seen = set()
for f in glob.glob(os.path.join(d, "*.json")):
    try:
        t = json.load(open(f))
    except Exception:
        continue
    if t.get("status") == "in_progress":
        o = t.get("owner")
        if o and o not in seen:
            seen.add(o); print(o)
PY
}

declare -A STATE    # key -> OK | STALLED  (survives across polls)
declare -A OWNERS   # owner-name -> 1  (rebuilt each poll)

owns_work() {
  # True if label $1 (or its agent-stripped form) owns an in_progress task.
  local l="$1"
  [ -n "${OWNERS[$l]:-}" ] && return 0
  [ -n "${OWNERS[${l#agent-}]:-}" ] && return 0
  return 1
}

evaluate_named() {
  # Task-ownership-gated. $1=label $2=activity-epoch.
  local key="$1" act_e="$2" idle state owns=0
  [[ "$act_e" =~ ^[0-9]+$ ]] || return 0          # no signal -> SKIP (no epoch-0)
  idle=$(( now - act_e ))
  state="${STATE[$key]:-OK}"
  owns_work "$key" && owns=1
  if [ "$idle" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$owns" -eq 1 ] && [ "$state" != "STALLED" ]; then
    STATE["$key"]="STALLED"
    printf 'STALL agent=%s idle=%ss task-owned=in_progress\n' "$key" "$idle"
  elif [ "$state" = "STALLED" ] && { [ "$idle" -lt "$resume_secs" ] || [ "$owns" -eq 0 ]; }; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
  fi
}

evaluate_anon() {
  # Ungated mtime rule for background subagents. $1=label $2=activity-epoch.
  local key="$1" act_e="$2" idle state
  [[ "$act_e" =~ ^[0-9]+$ ]] || return 0
  idle=$(( now - act_e ))
  state="${STATE[$key]:-OK}"
  if [ "$idle" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$state" != "STALLED" ]; then
    STATE["$key"]="STALLED"
    printf 'STALL agent=%s idle=%ss reason=subagent-idle\n' "$key" "$idle"
  elif [ "$state" = "STALLED" ] && [ "$idle" -lt "$resume_secs" ]; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
  fi
}

# ---- arg parsing ----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --team-dir)     [ $# -ge 2 ] || die "--team-dir needs a value";     team_dir="$2";     shift 2 ;;
    --tasks-dir)    [ $# -ge 2 ] || die "--tasks-dir needs a value";    tasks_dir="$2";    shift 2 ;;
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
[ "$have_py" -eq 1 ] || printf 'agent-watchdog: python3 not found; team + task-gate disabled, subagents only\n' >&2

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss team-dir=%s tasks-dir=%s projects-dir=%s worktrees=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "${team_dir:-<auto>}" "${tasks_dir:-<auto>}" "$projects_dir" "$worktrees_dir" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    sleep "$poll_secs" || true          # clock read failed -- skip, don't guess
    continue
  fi

  td="$team_dir"; [ -n "$td" ] || td="$(newest_path_in "$HOME/.claude/teams" -maxdepth 1 -type d -name 'session-*')"

  # ---- parse team config (members + lead session + team name) ----
  team_present=0; team_name=""; lead_session=""
  m_names=(); m_cwds=()
  if [ "$have_py" -eq 1 ] && [ -n "$td" ] && [ -f "$td/config.json" ]; then
    team_present=1
    while IFS=$'\t' read -r kind a b; do
      case "$kind" in
        NAME)   team_name="$a" ;;
        LEAD)   lead_session="$a" ;;
        MEMBER) m_names+=("$a"); m_cwds+=("$b") ;;
      esac
    done < <(parse_team "$td/config.json")
  fi

  # ---- resolve task store + build OWNERS_WITH_WORK ----
  tkdir="$tasks_dir"
  if [ -z "$tkdir" ] && [ -n "$team_name" ] && [ -d "$HOME/.claude/tasks/$team_name" ]; then
    tkdir="$HOME/.claude/tasks/$team_name"
  fi
  [ -n "$tkdir" ] || tkdir="$(newest_path_in "$HOME/.claude/tasks" -maxdepth 1 -type d -name 'session-*')"
  unset OWNERS; declare -A OWNERS
  if [ "$have_py" -eq 1 ] && [ -n "$tkdir" ] && [ -d "$tkdir" ]; then
    while IFS= read -r owner; do [ -n "$owner" ] && OWNERS["$owner"]=1; done < <(build_owners "$tkdir")
  fi

  unset SEEN; declare -A SEEN

  # global, best-effort: any build suppresses STALL for every agent this poll.
  build_active=0
  if pgrep -f 'cargo|rustc|go build|go test|node |pytest|jest|tsc|webpack|npm |pnpm |yarn ' >/dev/null 2>&1; then
    build_active=1
  fi

  # ---- SOURCE A: team members (NAMED, task-gated) ----
  if [ "$team_present" -eq 1 ]; then
    for i in "${!m_names[@]}"; do
      name="${m_names[$i]}"; cwd="${m_cwds[$i]}"
      [ -n "$name" ] || continue
      [ -n "${SEEN[$name]:-}" ] && continue
      SEEN["$name"]=1
      act=""
      wt="$worktrees_dir/agent-$name"
      if [ -d "$wt" ]; then
        SEEN["agent-$name"]=1                       # claim the worktree for Source C
        act="$(newest_mtime_under "$wt")"
      elif [ -n "$cwd" ]; then
        act="$(newest_mtime_under "$cwd")"
      fi
      [ -n "$act" ] || continue
      evaluate_named "$name" "$act"
    done
  fi

  # ---- SOURCE B: background subagent transcripts (ANONYMOUS, ungated) ----
  sub_dir=""
  if [ "$team_present" -eq 1 ]; then
    [ -n "$lead_session" ] && sub_dir="$(find "$projects_dir" -maxdepth 3 -type d -path "*/$lead_session/subagents" 2>/dev/null | head -n1 || true)"
  else
    sub_dir="$(find "$projects_dir" -maxdepth 4 -type f -path '*/subagents/agent-*.jsonl' -printf '%T@\t%h\n' 2>/dev/null | sort -rn | head -n1 | cut -f2- || true)"
  fi
  if [ -n "$sub_dir" ] && [ -d "$sub_dir" ]; then
    for f in "$sub_dir"/agent-*.jsonl; do
      [ -e "$f" ] || continue
      base="${f##*/}"; key="${base%.jsonl}"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      evaluate_anon "$key" "$(file_mtime "$f")"
    done
  fi

  # ---- SOURCE C: worktree-isolated agents (NAMED, task-gated) ----
  if [ -n "$worktrees_dir" ] && [ -d "$worktrees_dir" ]; then
    for d in "$worktrees_dir"/agent-*; do
      [ -d "$d" ] || continue
      key="${d##*/}"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      evaluate_named "$key" "$(newest_mtime_under "$d")"
    done
  fi

  sleep "$poll_secs" || true
done
