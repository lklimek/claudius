#!/usr/bin/env bash
# Agent-stall watchdog for multi-agent (grand-admiral) orchestration.
#
# Purpose
#   Fill the ONE gap the Claude Code harness does not cover: a NAMED agent that
#   OWNS assigned work yet has gone silent. The harness already auto-notifies on
#   completion AND death (crash / rate-limit / terminal error) with no approval,
#   so this is NOT the primary death detector.
#
# STALL == owns an in_progress task AND idle AT OR PAST the threshold (>=) AND no
# build running UNDER THAT AGENT (key correctness rule)
#   Bare idle is not a stall: a healthy agent idles while waiting for its next
#   instruction. A NAMED agent stalls only when it OWNS an in_progress task AND
#   its own activity clock has been idle >= stall_secs AND no build/test process
#   is running under its worktree/cwd. "Owns work" is read from the on-disk task
#   store (the source of truth). An idle agent owning no in_progress task is
#   healthy and NEVER fires.
#
# PER-AGENT build detection (NOT a machine-global pgrep)
#   A global `pgrep -f cargo|node|...` is wrong: on any shared box it matches
#   unrelated daemons (dashmate/yarn/etc.) and pins build_active=1 forever, so
#   the watchdog never fires. Instead, ONLY when a named agent is otherwise about
#   to STALL, scan /proc for a process whose `/proc/<pid>/cwd` resolves UNDER
#   that agent's worktree/cwd AND whose argv is a real build/test (anchored
#   argv0 basename + subcommand: cargo build|test|check|clippy|run, rustc, cc1,
#   cc1plus, gcc, g++, clang, clang++, ld, make, cmake, ninja, gradle, mvn,
#   bazel, go build|test|run, tsc, webpack, pytest, jest, dotnet build,
#   pip install). No global boolean; no bare node/npm/yarn/pnpm; no unanchored
#   substrings. /proc reads are guarded.
#
# PER-AGENT activity clock
#   1. If the agent's worktree `<worktrees>/agent-<name>` exists -> newest mtime
#      under it (INCLUDING its own target/ build dirs: its own build IS liveness).
#   2. Else its `cwd` (from config) -> newest mtime under it, EXCLUDING `.git`.
#      But if that cwd is shared by >=2 active members it cannot isolate one
#      agent -> SKIP that member with a one-time stderr note (give it a worktree).
#   3. Skip if neither yields an mtime (never epoch-0 / ~56-year alerts).
#
# ZERO MODEL TOKENS WHEN HEALTHY (hard contract)
#   Run by the `Monitor` tool, where each stdout LINE is a coordinator
#   notification costing tokens. Strictly EDGE-TRIGGERED: prints ONLY on an
#   OK->STALL or STALL->RESUMED transition. No heartbeat, no per-poll output, no
#   debug on stdout (diagnostics -> stderr). Healthy == silent stdout == 0 tokens.
#
# Monitor invocation (one persistent monitor per wave; autodetect by default):
#   Monitor(persistent=true, description="agent stall watchdog",
#           command="bash scripts/agent-watchdog.sh --stall-secs 300")
#   Prefer an explicit --team-dir when several sessions exist (autodetect picks
#   the newest dir by mtime, which a cleanup touch could mis-rank).
#
# CRITICAL -- a STALL line is a PRE-FILTER, never an auto-kill trigger
#   It prompts the coordinator to INVESTIGATE (read the transcript,
#   `git -C <cwd> status/diff`, confirm no build), THEN decide. Recovery
#   doctrine: grand-admiral skill.
#
# Three discovery sources (dedup by canonical label; team entry wins)
#   SOURCE A -- TEAM members (NAMED, task-gated): newest
#     ~/.claude/teams/session-*/config.json members with isActive==true AND
#     agentType != "team-lead". Canonical label = member `name`.
#   SOURCE C -- WORKTREE-isolated agents (NAMED, task-gated):
#     <worktrees>/agent-* dirs. Canonical label = dir name with a leading
#     "agent-" stripped, so A and C share ONE state key / output label.
#   SOURCE B -- INDIVIDUAL / background subagents (ANONYMOUS): OFF by default,
#     enable with --watch-subagents. agent-*.jsonl transcript mtime, idle-only.
#     Best-effort & opt-in: a finished subagent has a stale transcript by design
#     and there is no reliable on-disk completion signal, so this CANNOT tell
#     "completed" from "stuck" -- and the harness already notifies on background-
#     agent completion/death. Stale-STALLED keys are pruned when they stop being
#     discovered (see below), so a STALL is never permanently leaked.
#
# State-machine hygiene (transient-miss tolerant)
#   Liveness is an EVALUABLE signal (a usable mtime), not mere discovery. A key
#   is declared gone only after it produces NO live signal for `--gone-polls`
#   CONSECUTIVE polls (default 2); then it is cleared (`RESUMED agent=<key>
#   reason=gone`) and dropped from memory. A single-poll glitch (a partial
#   config write, a transient find/stat failure) therefore never spuriously
#   clears a STALL or drops state; one live poll resets the miss counter. This
#   handles removed worktrees / deactivated members while bounding state.
#
# Args (all optional; sane defaults shown)
#   --team-dir     DIR  team session dir w/ config.json
#                       (default: newest ~/.claude/teams/session-*)
#   --tasks-dir    DIR  task store (default: ~/.claude/tasks/<teamName> from the
#                       config `name`; fallback newest ~/.claude/tasks/session-*)
#   --projects-dir DIR  projects base for subagent transcripts
#                       (default: ~/.claude/projects)
#   --worktrees    DIR  worktree root holding agent-* dirs (default
#                       .claude/worktrees, resolved against the team root)
#   --watch-subagents   enable best-effort background-subagent monitoring (off)
#   --gone-polls   N    consecutive signalless polls before an agent is        (default: 2)
#                       declared gone (tolerates transient config/find misses)
#   --stall-secs   N    idle seconds (>=) before STALL             (default: 300)
#   --resume-secs  N    idle seconds (<) to declare RESUMED; must  (default: 60)
#                       be < --stall-secs
#   --poll-secs    N    seconds between polls                      (default: 45)
#
# Output (ONLY these line shapes ever reach stdout)
#   STALL agent=<name> idle=<N>s reason=owns-in_progress-idle   (named: A, C)
#   STALL agent=<key>  idle=<N>s reason=subagent-idle           (anonymous: B)
#   RESUMED agent=<key> idle=<N>s        | RESUMED agent=<key> reason=gone
#
# Exit: runs forever; transient stat/find/proc/python3 failures are swallowed
# (|| true) so a momentary hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
team_dir=""
tasks_dir=""
projects_dir="$HOME/.claude/projects"
worktrees_dir=".claude/worktrees"
watch_subagents=0
gone_polls=2
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
                         [--worktrees DIR] [--watch-subagents] [--gone-polls N]
                         [--stall-secs N] [--resume-secs N] [--poll-secs N]
STALL = owns an in_progress task AND idle >= threshold AND no build under the
agent's worktree/cwd. An idle agent owning no in_progress task is never flagged.
Emits ONLY 'STALL'/'RESUMED' transition lines to stdout; diagnostics to stderr.
USAGE
}

newest_mtime_under() {            # newest mtime of ANY entry under $1 (incl. build dirs)
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -printf '%T@\n' 2>/dev/null | sort -rn | head -n1 || true)"
  printf '%s' "${m%.*}"
}

newest_mtime_cwd() {              # like above but pruning .git (shared-repo noise)
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -name .git -prune -o -printf '%T@\n' 2>/dev/null | sort -rn | head -n1 || true)"
  printf '%s' "${m%.*}"
}

newest_path_in() {
  local dir="$1"; shift
  [ -d "$dir" ] || return 0
  find "$dir" "$@" -printf '%T@\t%p\n' 2>/dev/null | sort -rn | head -n1 | cut -f2- || true
}

canon() { local l="$1"; printf '%s' "${l#agent-}"; }   # strip one leading agent-

parse_team() {
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
        continue                      # partial write -> tolerate, retry next poll
    if t.get("status") == "in_progress":
        o = t.get("owner")
        if o and o not in seen:
            seen.add(o); print(o)
PY
}

is_build_proc() {
  # True if pid $1's argv is an anchored build/test command.
  local pid="$1" cmd="/proc/$1/cmdline" a0="" a1="" a2="" a3=""
  [ -r "$cmd" ] || return 1
  { IFS= read -r -d '' a0 || true
    IFS= read -r -d '' a1 || true
    IFS= read -r -d '' a2 || true
    IFS= read -r -d '' a3 || true
  } < "$cmd" 2>/dev/null || return 1
  a0="${a0##*/}"                       # argv0 basename
  case "$a0" in
    rustc|cc1|cc1plus|gcc|g++|clang|clang++|ld|make|cmake|ninja|gradle|mvn|bazel|tsc|webpack|pytest|jest) return 0 ;;
    cargo)    case "$a1" in build|test|check|clippy|run) return 0 ;; esac ;;
    go)       case "$a1" in build|test|run) return 0 ;; esac ;;
    dotnet)   [ "$a1" = build ] && return 0 ;;
    pip|pip3) [ "$a1" = install ] && return 0 ;;
    python|python3)
      case "$a1" in
        -m) case "$a2" in pytest) return 0 ;; pip) [ "$a3" = install ] && return 0 ;; esac ;;
      esac ;;
  esac
  return 1
}

build_active_under() {
  # True if a real build/test runs with /proc cwd under $1 (per-agent scope).
  local dir="$1" pid cwd
  [ -n "$dir" ] || return 1
  dir="$(readlink -f -- "$dir" 2>/dev/null || printf '%s' "$dir")"; dir="${dir%/}"
  for p in /proc/[0-9]*; do
    pid="${p##*/}"
    cwd="$(readlink -f -- "/proc/$pid/cwd" 2>/dev/null || true)"
    [ -n "$cwd" ] || continue
    case "$cwd/" in "$dir/"*) ;; *) continue ;; esac   # cwd == dir or under it
    is_build_proc "$pid" && return 0
  done
  return 1
}

declare -A STATE      # canonical key -> OK | STALLED (persists across polls)
declare -A OWNERS     # owner name -> 1 (rebuilt each poll)
declare -A WARNED     # one-time stderr notes already emitted
declare -A MISS       # key -> consecutive polls with NO live signal (gone grace)
declare -A ALIVE      # key -> 1 if it produced an evaluable signal THIS poll

owns_work() {
  local l="$1"
  [ -n "${OWNERS[$l]:-}" ] && return 0
  [ -n "${OWNERS[agent-$l]:-}" ] && return 0
  return 1
}

warn_once() { local k="$1"; [ -n "${WARNED[$k]:-}" ] && return 0; WARNED["$k"]=1; printf 'agent-watchdog: %s\n' "$2" >&2; }

evaluate_named() {
  # $1=canonical label  $2=activity epoch  $3=agent dir (worktree/cwd)
  local key="$1" act_e="$2" dir="$3" idle state owns=0
  [[ "$act_e" =~ ^[0-9]+$ ]] || return 0    # no evaluable signal -> not "alive" this poll
  ALIVE["$key"]=1
  idle=$(( now - act_e ))
  state="${STATE[$key]:-OK}"
  owns_work "$key" && owns=1
  if [ "$idle" -ge "$stall_secs" ] && [ "$owns" -eq 1 ] && [ "$state" != "STALLED" ]; then
    if ! build_active_under "$dir"; then          # per-agent build suppression
      STATE["$key"]="STALLED"
      printf 'STALL agent=%s idle=%ss reason=owns-in_progress-idle\n' "$key" "$idle"
    fi
  elif [ "$state" = "STALLED" ] && { [ "$idle" -lt "$resume_secs" ] || [ "$owns" -eq 0 ]; }; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s idle=%ss\n' "$key" "$idle"
  fi
}

evaluate_anon() {
  local key="$1" act_e="$2" idle state
  [[ "$act_e" =~ ^[0-9]+$ ]] || return 0
  ALIVE["$key"]=1
  idle=$(( now - act_e ))
  state="${STATE[$key]:-OK}"
  if [ "$idle" -ge "$stall_secs" ] && [ "$state" != "STALLED" ]; then
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
    --team-dir)       [ $# -ge 2 ] || die "--team-dir needs a value";     team_dir="$2";     shift 2 ;;
    --tasks-dir)      [ $# -ge 2 ] || die "--tasks-dir needs a value";    tasks_dir="$2";    shift 2 ;;
    --projects-dir)   [ $# -ge 2 ] || die "--projects-dir needs a value"; projects_dir="$2"; shift 2 ;;
    --worktrees)      [ $# -ge 2 ] || die "--worktrees needs a value";    worktrees_dir="$2"; shift 2 ;;
    --watch-subagents) watch_subagents=1; shift ;;
    --gone-polls)     [ $# -ge 2 ] || die "--gone-polls needs a value";   require_int "$1" "$2"; gone_polls="$2";  shift 2 ;;
    --stall-secs)     [ $# -ge 2 ] || die "--stall-secs needs a value";   require_int "$1" "$2"; stall_secs="$2";  shift 2 ;;
    --resume-secs)    [ $# -ge 2 ] || die "--resume-secs needs a value";  require_int "$1" "$2"; resume_secs="$2"; shift 2 ;;
    --poll-secs)      [ $# -ge 2 ] || die "--poll-secs needs a value";    require_int "$1" "$2"; poll_secs="$2";   shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ "$poll_secs" -ge 1 ] || die "--poll-secs must be >= 1"
[ "$gone_polls" -ge 1 ] || die "--gone-polls must be >= 1"
[ "$resume_secs" -lt "$stall_secs" ] || die "--resume-secs ($resume_secs) must be < --stall-secs ($stall_secs)"

command -v python3 >/dev/null 2>&1 || die "python3 not found (required to read team config + task store)"
# GNU find/stat probe -- the mtime clocks are GNU-only; fail loud, not silent.
stat -c %Y "$0" >/dev/null 2>&1 || die "GNU stat (stat -c %Y) required"
find "$0" -maxdepth 0 -printf '' >/dev/null 2>&1 || die "GNU find (find -printf) required"

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss gone-polls=%s team-dir=%s tasks-dir=%s worktrees=%s watch-subagents=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "$gone_polls" "${team_dir:-<auto>}" "${tasks_dir:-<auto>}" "$worktrees_dir" "$watch_subagents" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    sleep "$poll_secs" || true
    continue
  fi

  td="$team_dir"; [ -n "$td" ] || td="$(newest_path_in "$HOME/.claude/teams" -maxdepth 1 -type d -name 'session-*')"

  # ---- parse team config ----
  team_present=0; team_name=""; lead_session=""
  m_names=(); m_cwds=()
  if [ -n "$td" ] && [ -f "$td/config.json" ]; then
    team_present=1
    while IFS=$'\t' read -r kind a b; do
      case "$kind" in
        NAME)   team_name="$a" ;;
        LEAD)   lead_session="$a" ;;
        MEMBER) m_names+=("$a"); m_cwds+=("$b") ;;
      esac
    done < <(parse_team "$td/config.json")
    if [ "${#m_names[@]}" -eq 0 ] && [ -z "$lead_session" ]; then
      warn_once "cfgparse:$td" "team config at $td unreadable/partial; Source A empty this poll"
    fi
  fi

  # ---- resolve task store + OWNERS_WITH_WORK ----
  tkdir="$tasks_dir"
  if [ -z "$tkdir" ] && [ -n "$team_name" ] && [ -d "$HOME/.claude/tasks/$team_name" ]; then
    tkdir="$HOME/.claude/tasks/$team_name"
  fi
  [ -n "$tkdir" ] || tkdir="$(newest_path_in "$HOME/.claude/tasks" -maxdepth 1 -type d -name 'session-*')"
  unset OWNERS; declare -A OWNERS
  if [ -n "$tkdir" ] && [ -d "$tkdir" ]; then
    while IFS= read -r owner; do [ -n "$owner" ] && OWNERS["$owner"]=1; done < <(build_owners "$tkdir")
  fi

  # ---- resolve worktrees root (default relative -> team root) ----
  wt_dir="$worktrees_dir"
  case "$wt_dir" in
    /*) : ;;
    *) [ -n "${m_cwds[0]:-}" ] && wt_dir="${m_cwds[0]%/}/$worktrees_dir" ;;
  esac

  # ---- count active-member cwds (shared-cwd detection) ----
  unset CWD_COUNT; declare -A CWD_COUNT
  if [ "$team_present" -eq 1 ]; then
    for i in "${!m_names[@]}"; do
      c="${m_cwds[$i]}"; [ -n "$c" ] && CWD_COUNT["$c"]=$(( ${CWD_COUNT[$c]:-0} + 1 ))
    done
  fi

  unset SEEN ALIVE; declare -A SEEN ALIVE   # SEEN = dedup; ALIVE = had a live signal

  # ---- SOURCE A: team members (NAMED, gated) ----
  if [ "$team_present" -eq 1 ]; then
    for i in "${!m_names[@]}"; do
      name="${m_names[$i]}"; cwd="${m_cwds[$i]}"
      [ -n "$name" ] || continue
      key="$(canon "$name")"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      wt="$wt_dir/agent-$key"
      if [ -d "$wt" ]; then
        evaluate_named "$key" "$(newest_mtime_under "$wt")" "$wt"
      elif [ -n "$cwd" ] && [ "${CWD_COUNT[$cwd]:-0}" -ge 2 ]; then
        warn_once "sharedcwd:$key" "no per-agent signal for $key (cwd shared by >=2 active members) — give it an isolated worktree to monitor"
      elif [ -n "$cwd" ]; then
        evaluate_named "$key" "$(newest_mtime_cwd "$cwd")" "$cwd"
      fi
    done
  fi

  # ---- SOURCE C: worktree-isolated agents (NAMED, gated) ----
  if [ -n "$wt_dir" ] && [ -d "$wt_dir" ]; then
    for d in "$wt_dir"/agent-*; do
      [ -d "$d" ] || continue
      key="$(canon "${d##*/}")"
      [ -n "${SEEN[$key]:-}" ] && continue
      SEEN["$key"]=1
      evaluate_named "$key" "$(newest_mtime_under "$d")" "$d"
    done
  elif [ -n "$wt_dir" ]; then
    warn_once "nowt:$wt_dir" "worktrees dir $wt_dir absent; Source C inactive"
  fi

  # ---- SOURCE B: background subagents (ANONYMOUS, opt-in) ----
  if [ "$watch_subagents" -eq 1 ]; then
    sub_dirs=()
    if [ "$team_present" -eq 1 ] && [ -n "$lead_session" ]; then
      d="$(find "$projects_dir" -maxdepth 3 -type d -path "*/$lead_session/subagents" 2>/dev/null | head -n1 || true)"
      [ -n "$d" ] && sub_dirs+=("$d")
    else
      # no team / unparsable config -> enumerate ALL subagents dirs in newest slug
      slug="$(newest_path_in "$projects_dir" -mindepth 1 -maxdepth 1 -type d)"
      if [ -n "$slug" ]; then
        while IFS= read -r d; do [ -n "$d" ] && sub_dirs+=("$d"); done \
          < <(find "$slug" -maxdepth 2 -type d -name subagents 2>/dev/null || true)
      fi
    fi
    for d in "${sub_dirs[@]:-}"; do
      { [ -n "$d" ] && [ -d "$d" ]; } || continue
      for f in "$d"/agent-*.jsonl; do
        [ -e "$f" ] || continue
        base="${f##*/}"; key="${base%.jsonl}"
        [ -n "${SEEN[$key]:-}" ] && continue
        SEEN["$key"]=1
        m="$(stat -c %Y "$f" 2>/dev/null || true)"
        evaluate_anon "$key" "$m"
      done
    done
  fi

  # ---- state-machine hygiene (QA-015/QA-016): gone only after N misses ----
  # Liveness is an EVALUABLE signal (ALIVE), not mere discovery. An agent must
  # be signalless for `gone_polls` CONSECUTIVE polls before it is declared gone,
  # so a one-poll config-parse glitch / find hiccup never spuriously clears a
  # STALL or drops state. A live poll resets the miss counter.
  for key in "${!STATE[@]}"; do
    if [ -n "${ALIVE[$key]:-}" ]; then
      MISS["$key"]=0
      continue
    fi
    MISS["$key"]=$(( ${MISS[$key]:-0} + 1 ))
    if [ "${MISS[$key]}" -ge "$gone_polls" ]; then
      [ "${STATE[$key]}" = "STALLED" ] && printf 'RESUMED agent=%s reason=gone\n' "$key"
      unset 'STATE[$key]' 'MISS[$key]'
    fi
  done

  sleep "$poll_secs" || true
done
