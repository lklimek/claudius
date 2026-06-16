#!/usr/bin/env bash
# Agent-stall watchdog for multi-agent (grand-admiral) orchestration.
#
# Purpose:
#   Fill the ONE gap the Claude Code harness does not cover: an agent that is
#   silently stuck but has NOT crashed. The harness already auto-notifies on
#   completion AND on death (crash / rate-limit / terminal error) with no
#   approval needed -- so this watchdog is NOT the primary death detector. It
#   only flags "alive but went quiet" so the coordinator can investigate.
#
# Monitor invocation (one persistent monitor per wave; each stdout line is one
# notification, so output is deliberately sparse):
#   Monitor(persistent=true, description="agent stall watchdog",
#           command="bash scripts/agent-watchdog.sh \
#                      --worktrees .claude/worktrees --stall-secs 300")
#
# CRITICAL -- a STALL line is a PRE-FILTER, never an auto-kill trigger:
#   STALL means "idle long enough AND no build running" -- it is a prompt for
#   the coordinator to INVESTIGATE (tail the transcript, `git -C <worktree>
#   status/diff`, confirm no build), THEN decide. Restarting a busy agent
#   destroys its in-flight work. The recovery doctrine lives in the
#   grand-admiral skill (## Recovery).
#
# Why two design choices look "too conservative" -- they are, on purpose:
#   * Build-activity suppression: a HEALTHY agent blocked on one long tool call
#     (a cold `cargo` build can run 10-20 min) writes nothing, so transcript
#     mtime alone reads as "idle". Therefore ANY running build (cargo / rustc /
#     go / node / pytest / jest / tsc / webpack / npm / pnpm / yarn) suppresses
#     STALL for ALL agents this poll. Attribution is intentionally coarse and
#     global: a false "OK" is cheap (next poll re-checks); a false STALL that
#     gets an agent killed mid-build is expensive.
#   * No epoch fallback: liveness is the NEWEST mtime across {the agent's
#     transcript file, every entry under its worktree}. If an agent has NO files
#     yet this poll, it is SKIPPED -- never defaulted to mtime 0. Defaulting to
#     the Unix epoch computes idle against 1970 and emits bogus ~56-year STALLs.
#
# Args (all optional; sane defaults shown):
#   --transcripts DIR   transcript dir (default: newest ~/.claude/projects/*/)
#   --worktrees   DIR   worktree root  (default: .claude/worktrees)
#   --stall-secs  N     idle seconds before STALL          (default: 300)
#   --resume-secs N     idle seconds below which a STALLED  (default: 60)
#                       agent is declared RESUMED
#   --poll-secs   N     seconds between polls               (default: 45)
#
# Output (ONLY these two line shapes -- Monitor auto-stops noisy monitors):
#   STALL agent=<name> idle=<N>s transcript=<path>
#   RESUMED agent=<name> idle=<N>s
#
# Exit: runs forever; transient stat/find/pgrep failures are swallowed (|| true)
# so a momentary filesystem hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
transcripts_dir=""
worktrees_dir=".claude/worktrees"
stall_secs=300
resume_secs=60
poll_secs=45

# ---- arg parsing ----------------------------------------------------------
die() { printf 'agent-watchdog: %s\n' "$1" >&2; exit 1; }

require_int() {
  # $1 = flag name, $2 = value
  [[ "$2" =~ ^[0-9]+$ ]] || die "$1 expects a non-negative integer, got: $2"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --transcripts) [ $# -ge 2 ] || die "--transcripts needs a value"; transcripts_dir="$2"; shift 2 ;;
    --worktrees)   [ $# -ge 2 ] || die "--worktrees needs a value";   worktrees_dir="$2";   shift 2 ;;
    --stall-secs)  [ $# -ge 2 ] || die "--stall-secs needs a value";  require_int "$1" "$2"; stall_secs="$2";  shift 2 ;;
    --resume-secs) [ $# -ge 2 ] || die "--resume-secs needs a value"; require_int "$1" "$2"; resume_secs="$2"; shift 2 ;;
    --poll-secs)   [ $# -ge 2 ] || die "--poll-secs needs a value";   require_int "$1" "$2"; poll_secs="$2";   shift 2 ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; $d'
      exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ "$poll_secs" -ge 1 ] || die "--poll-secs must be >= 1"

# ---- autodetect transcripts dir if unset ----------------------------------
if [ -z "$transcripts_dir" ]; then
  base="$HOME/.claude/projects"
  if [ -d "$base" ]; then
    # newest project subdir by mtime; never hard-fail on a glob miss
    transcripts_dir="$(
      find "$base" -mindepth 1 -maxdepth 1 -type d -printf '%T@\t%p\n' 2>/dev/null \
        | sort -rn | head -n1 | cut -f2- || true
    )"
  fi
fi

# ---- per-agent state survives across polls --------------------------------
declare -A STATE   # key -> OK | STALLED

# act: scratch global updated by update_max (must NOT run in a subshell).
act=""
update_max() {
  # Fold candidate epoch $1 into $act, keeping the larger. Empty candidate is
  # a no-op so a missing signal never resets liveness to a smaller/zero value.
  local cand="$1"
  [ -n "$cand" ] || return 0
  [[ "$cand" =~ ^[0-9]+$ ]] || return 0
  if [ -z "$act" ] || [ "$cand" -gt "$act" ]; then
    act="$cand"
  fi
}

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss transcripts=%s worktrees=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "${transcripts_dir:-<none>}" "$worktrees_dir" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    # clock read failed -- skip this poll rather than computing garbage idle
    sleep "$poll_secs" || true
    continue
  fi

  # Rediscover agents every poll (membership changes as waves spawn/finish).
  unset TRANSCRIPT WORKTREE SEEN
  declare -A TRANSCRIPT WORKTREE SEEN

  if [ -n "$transcripts_dir" ] && [ -d "$transcripts_dir" ]; then
    for f in "$transcripts_dir"/agent-*.jsonl; do
      [ -e "$f" ] || continue          # glob miss -> literal pattern, skip
      base="${f##*/}"; key="${base#agent-}"; key="${key%.jsonl}"
      TRANSCRIPT["$key"]="$f"
    done
  fi

  if [ -n "$worktrees_dir" ] && [ -d "$worktrees_dir" ]; then
    for d in "$worktrees_dir"/agent-*; do
      [ -d "$d" ] || continue
      base="${d##*/}"; key="${base#agent-}"
      WORKTREE["$key"]="$d"
    done
  fi

  # build activity is global + best-effort: one check suppresses STALL for all.
  build_active=0
  if pgrep -f 'cargo|rustc|go build|go test|node |pytest|jest|tsc|webpack|npm |pnpm |yarn ' >/dev/null 2>&1; then
    build_active=1
  fi

  for key in "${!TRANSCRIPT[@]}" "${!WORKTREE[@]}"; do
    [ -n "${SEEN[$key]:-}" ] && continue   # union of both sources, once each
    SEEN["$key"]=1

    tpath="${TRANSCRIPT[$key]:-}"
    wpath="${WORKTREE[$key]:-}"

    act=""
    if [ -n "$tpath" ] && [ -e "$tpath" ]; then
      update_max "$(stat -c %Y "$tpath" 2>/dev/null || true)"
    fi
    if [ -n "$wpath" ] && [ -d "$wpath" ]; then
      # newest mtime of ANY entry (files + dirs) under the worktree; %T@ is a
      # float, keep the integer seconds part.
      wt="$(find "$wpath" -printf '%T@\n' 2>/dev/null | sort -rn | head -n1 || true)"
      update_max "${wt%.*}"
    fi

    # No files for this agent this poll -> SKIP (never epoch-0 / ~56yr STALL).
    [ -n "$act" ] || continue

    idle=$(( now - act ))
    state="${STATE[$key]:-OK}"
    ref="${tpath:-$wpath}"

    if [ "$idle" -ge "$stall_secs" ] && [ "$build_active" -eq 0 ] && [ "$state" != "STALLED" ]; then
      STATE["$key"]="STALLED"
      printf 'STALL agent=%s idle=%ss transcript=%s\n' "$key" "$idle" "$ref"
    elif [ "$state" = "STALLED" ] && [ "$idle" -lt "$resume_secs" ]; then
      STATE["$key"]="OK"
      printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
    fi
  done

  sleep "$poll_secs" || true
done
