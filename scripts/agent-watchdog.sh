#!/usr/bin/env bash
# Agent-stall watchdog for multi-agent (grand-admiral) orchestration.
#
# Purpose
#   Fill the ONE gap the Claude Code harness does not cover: an agent that is
#   silently stuck but has NOT crashed. The harness already auto-notifies on
#   completion AND on death (crash / rate-limit / terminal error) with no
#   approval -- so this watchdog is NOT the primary death detector. It only
#   flags "alive but went quiet" so the coordinator can investigate.
#
# ZERO MODEL TOKENS WHEN HEALTHY (hard contract)
#   This script is run by the `Monitor` tool, where every stdout LINE becomes a
#   coordinator notification that costs context tokens. Therefore it is strictly
#   EDGE-TRIGGERED: it prints a line ONLY on an OK->STALL or STALL->RESUMED
#   transition. There is NO per-poll output, NO heartbeat, NO "all clear", NO
#   progress, and NO debug on stdout (all diagnostics go to stderr). Healthy
#   operation == total stdout silence == zero coordinator tokens. Tokens are
#   spent only when a real stall fires (and then recovery is worth it).
#
# Monitor invocation (one persistent monitor per wave; autodetect by default):
#   Monitor(persistent=true, description="agent stall watchdog",
#           command="bash scripts/agent-watchdog.sh --stall-secs 300")
#
# CRITICAL -- a STALL line is a PRE-FILTER, never an auto-kill trigger
#   STALL means "idle long enough AND no build running". It is a prompt for the
#   coordinator to INVESTIGATE (tail the transcript, `git -C <cwd> status/diff`,
#   confirm no build), THEN decide. Restarting a busy agent destroys in-flight
#   work. The recovery doctrine lives in the grand-admiral skill (## Recovery).
#
# Two agent sources (UNION; identical thresholds/logic applied to each)
#   SOURCE 1 -- TEAM agents: newest ~/.claude/teams/session-*/config.json ->
#     members[] with isActive==true (this excludes BOTH the coordinator, which
#     has no isActive field, AND finished members, isActive:false). Label = the
#     member `name`. Activity = newest mtime under the member's `cwd` PLUS the
#     mtime of its inbox file (inboxes/<name>.json). When members share a cwd
#     (non-isolated runs) the cwd signal is shared; the per-name inbox mtime is
#     then the only per-agent differentiator -- attribution is coarse by design.
#   SOURCE 2 -- INDIVIDUAL / background subagents: nested transcripts at
#     ~/.claude/projects/<slug>/<lead-uuid>/subagents/agent-<id>.jsonl. Label =
#     the `agent-<id>` filename stem. Activity = the transcript file's OWN mtime
#     (the per-agent activity clock, attributable by filename). Discovery is
#     scoped to the NEWEST subagents dir under the project, which naturally
#     drops completed agents from prior lead sessions. A transcript persists
#     after an agent finishes, so a long-idle subagent + no build is a STALL
#     CANDIDATE the coordinator confirms (the harness already notified on a real
#     completion/crash) -- not a guaranteed hang.
#   Dedup: a key is watched once; SOURCE 1 is processed first, so any collision
#   prefers the team-config entry. (The two sources use distinct label spaces --
#   `name` vs `agent-<id>` -- so real overlap is rare; the dedup set is a guard.)
#
# Cross-checks (both sources)
#   * build_active: a single global `pgrep` (cargo|rustc|go|node|pytest|tsc|
#     npm|pnpm|yarn) suppresses STALL for ALL agents this poll. A HEALTHY agent
#     blocked on one long cold build (10-20 min) writes nothing, so mtime alone
#     reads as "idle"; any running build conservatively suppresses STALL.
#     Attribution is intentionally coarse and global: a false "OK" is cheap
#     (next poll re-checks); a false STALL that kills a building agent is not.
#   * NO epoch fallback: if an agent has NO files this poll, it is SKIPPED --
#     never defaulted to mtime 0. Defaulting to the Unix epoch computes idle
#     against 1970 and emits bogus ~56-year STALLs.
#   * `isActive` is treated as a hint to choose WHICH members to watch; it may
#     lag (like idle_notification) and is never the sole truth for a stall --
#     the mtime+build evidence and coordinator investigation decide.
#
# Args (all optional; sane defaults shown)
#   --team-dir    DIR  team session dir w/ config.json + inboxes/
#                      (default: newest ~/.claude/teams/session-*)
#   --project-dir DIR  project slug dir holding <uuid>/subagents/agent-*.jsonl
#                      (default: newest ~/.claude/projects/*)
#   --stall-secs  N    idle seconds before STALL                  (default: 300)
#   --resume-secs N    idle seconds below which a STALLED agent    (default: 60)
#                      is declared RESUMED
#   --poll-secs   N    seconds between polls                       (default: 45)
#
# Output (ONLY these two line shapes ever reach stdout)
#   STALL agent=<key> idle=<N>s src=<team|subagent> ref=<path>
#   RESUMED agent=<key> idle=<N>s
#
# Exit: runs forever; transient stat/find/pgrep/jq failures are swallowed
# (|| true) so a momentary filesystem hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
team_dir=""
project_dir=""
stall_secs=300
resume_secs=60
poll_secs=45

# ---- helpers --------------------------------------------------------------
die() { printf 'agent-watchdog: %s\n' "$1" >&2; exit 1; }

require_int() { [[ "$2" =~ ^[0-9]+$ ]] || die "$1 expects a non-negative integer, got: $2"; }

usage() {
  cat >&2 <<'USAGE'
agent-watchdog.sh -- edge-triggered agent-stall watchdog (silent when healthy)
Usage: agent-watchdog.sh [--team-dir DIR] [--project-dir DIR]
                         [--stall-secs N] [--resume-secs N] [--poll-secs N]
Defaults: team-dir=newest ~/.claude/teams/session-*
          project-dir=newest ~/.claude/projects/*
          stall=300 resume=60 poll=45
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

# act: scratch global folded by update_max (must NOT run in a subshell).
act=""
update_max() {
  # Fold candidate epoch $1 into $act, keeping the larger. An empty/non-numeric
  # candidate is a no-op so a missing signal never lowers liveness.
  local cand="$1"
  [[ "$cand" =~ ^[0-9]+$ ]] || return 0
  if [ -z "$act" ] || [ "$cand" -gt "$act" ]; then act="$cand"; fi
}

declare -A STATE   # key -> OK | STALLED  (survives across polls)

evaluate() {
  # Edge-triggered state machine. Reads globals: act, now, build_active,
  # stall_secs, resume_secs, STATE. $1=key $2=src $3=ref-path
  local key="$1" src="$2" ref="$3"
  local idle=$(( now - act ))
  local state="${STATE[$key]:-OK}"
  if [ "$idle" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$state" != "STALLED" ]; then
    STATE["$key"]="STALLED"
    printf 'STALL agent=%s idle=%ss src=%s ref=%s\n' "$key" "$idle" "$src" "$ref"
  elif [ "$state" = "STALLED" ] && [ "$idle" -lt "$resume_secs" ]; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
  fi
}

# ---- arg parsing ----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --team-dir)    [ $# -ge 2 ] || die "--team-dir needs a value";    team_dir="$2";    shift 2 ;;
    --project-dir) [ $# -ge 2 ] || die "--project-dir needs a value"; project_dir="$2"; shift 2 ;;
    --stall-secs)  [ $# -ge 2 ] || die "--stall-secs needs a value";  require_int "$1" "$2"; stall_secs="$2";  shift 2 ;;
    --resume-secs) [ $# -ge 2 ] || die "--resume-secs needs a value"; require_int "$1" "$2"; resume_secs="$2"; shift 2 ;;
    --poll-secs)   [ $# -ge 2 ] || die "--poll-secs needs a value";   require_int "$1" "$2"; poll_secs="$2";   shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ "$poll_secs" -ge 1 ] || die "--poll-secs must be >= 1"

# jq is required only for SOURCE 1 (team config). Without it, watch subagents.
have_jq=0
if command -v jq >/dev/null 2>&1; then have_jq=1; fi
[ "$have_jq" -eq 1 ] || printf 'agent-watchdog: jq not found; team-config source disabled, subagent transcripts only\n' >&2

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss team-dir=%s project-dir=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "${team_dir:-<auto>}" "${project_dir:-<auto>}" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    sleep "$poll_secs" || true        # clock read failed -- skip, don't guess
    continue
  fi

  # Resolve dirs each poll (membership + autodetect target can change).
  td="$team_dir";    [ -n "$td" ] || td="$(newest_path_in "$HOME/.claude/teams" -maxdepth 1 -type d -name 'session-*')"
  pd="$project_dir"; [ -n "$pd" ] || pd="$(newest_path_in "$HOME/.claude/projects" -mindepth 1 -maxdepth 1 -type d)"

  unset SEEN; declare -A SEEN

  # global, best-effort: any build suppresses STALL for every agent this poll.
  build_active=0
  if pgrep -f 'cargo|rustc|go build|go test|node |pytest|jest|tsc|webpack|npm |pnpm |yarn ' >/dev/null 2>&1; then
    build_active=1
  fi

  # ---- SOURCE 1: team members (isActive==true) ----
  if [ "$have_jq" -eq 1 ] && [ -n "$td" ] && [ -f "$td/config.json" ]; then
    while IFS=$'\t' read -r name cwd; do
      [ -n "$name" ] || continue
      [ -n "${SEEN[$name]:-}" ] && continue
      SEEN["$name"]=1
      act=""
      [ -n "$cwd" ] && update_max "$(newest_mtime_under "$cwd")"
      update_max "$(file_mtime "$td/inboxes/$name.json")"
      [ -n "$act" ] || continue          # no files -> SKIP (never epoch-0)
      evaluate "$name" "team" "${cwd:-$td/inboxes/$name.json}"
    done < <(jq -r '.members[]? | select(.isActive == true) | [.name, (.cwd // "")] | @tsv' "$td/config.json" 2>/dev/null || true)
  fi

  # ---- SOURCE 2: individual / background subagent transcripts ----
  if [ -n "$pd" ] && [ -d "$pd" ]; then
    sub_dir="$(newest_path_in "$pd" -maxdepth 2 -type d -name subagents)"
    if [ -n "$sub_dir" ] && [ -d "$sub_dir" ]; then
      for f in "$sub_dir"/agent-*.jsonl; do
        [ -e "$f" ] || continue          # glob miss -> literal pattern, skip
        base="${f##*/}"; key="${base%.jsonl}"
        [ -n "${SEEN[$key]:-}" ] && continue
        SEEN["$key"]=1
        act=""
        update_max "$(file_mtime "$f")"
        [ -n "$act" ] || continue
        evaluate "$key" "subagent" "$f"
      done
    fi
  fi

  sleep "$poll_secs" || true
done
