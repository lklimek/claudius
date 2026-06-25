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
#   cc1plus, gcc, g++, clang, clang++, ld, make, cmake, ninja, gradle, gradlew,
#   mvn, mvnw, bazel, go build|test|run, tsc, webpack, pytest, jest, dotnet
#   build, pip install). Shebang/interpreter wrappers are unwrapped one layer
#   (sh ./gradlew, env bash ./mvnw, python3 .../pytest, node .../jest) so a
#   wrapped build is matched on argv1/argv2, not just argv0. No global boolean;
#   no bare node/npm/yarn/pnpm; no unanchored substrings. /proc reads guarded.
#
# PER-AGENT activity clock
#   1. If the agent's worktree `<worktrees>/agent-<name>` exists -> newest mtime
#      under it (INCLUDING its own target/ build dirs: its own build IS liveness).
#   2. Else its `cwd` (from config) -> newest mtime under it, EXCLUDING `.git`.
#   3. Else (cwd shared by >=2 active members, so its mtime is polluted by the
#      lead/another member) -> TRANSCRIPT-MTIME FALLBACK: the member's own
#      transcript jsonl (…/<leadSession>/subagents/agent-<id>.jsonl matched by the
#      internal agentId, or …/<cwd-slug>/<ownSession>.jsonl matched by a unique
#      agentSetting==agentType). The transcript advances on EVERY agent turn, so it
#      is a reliable activity clock even for read-only design/QA agents that share
#      the lead's cwd and write outputs to /tmp. Only if no transcript resolves is
#      the member skipped with a one-time stderr note (give it a worktree).
#   4. Skip if none yields an mtime (never epoch-0 / ~56-year alerts).
#
# PROCESS-LIVENESS / GONE (verified absence, distinct from STALL)
#   STALL means "process alive but idle while owning work" -- a PRE-FILTER to
#   investigate. GONE means the agent PROCESS is verifiably ABSENT while the team
#   still believes it active (config isActive==true). For a tmux-backed member the
#   recorded `tmuxPaneId` is probed each poll:
#     pane-dead  -- the pane's `pane_current_command` reverted to a bare shell
#                   (sh/bash/zsh/-bash/dash/ksh/fish/login); the agent's claude/
#                   node process exited but the pane lives. (A live claude pane
#                   reports a non-shell command such as its version string.)
#     pid-gone   -- the recorded pane no longer exists in an otherwise-reachable
#                   tmux server (>=1 sibling configured pane still resolves -> not
#                   a wrong-socket false positive); pane + process destroyed.
#     stale-active -- a process-absent signal (pane-dead or pane-gone) CORROBORATED
#                   by a stale activity/transcript clock (idle >= stall_secs):
#                   highest-confidence proof the isActive flag is stale.
#   GONE requires --gone-polls CONSECUTIVE confirmations (same anti-glitch backstop
#   as the gone-prune) and is edge-triggered. It NEVER auto-kills: it suggests the
#   coordinator clear the stale active flag / respawn. If a GONE pane shows a live
#   command again it recovers (`RESUMED agent=<name> reason=recovered`). Disable
#   the whole GONE layer with --no-gone; it is a no-op without tmux or a config.
#
# ZERO MODEL TOKENS WHEN HEALTHY (hard contract)
#   Run by the `Monitor` tool, where each stdout LINE is a coordinator
#   notification costing tokens. Strictly EDGE-TRIGGERED: prints ONLY on an
#   OK->STALL or STALL->RESUMED transition. No heartbeat, no per-poll output, no
#   debug on stdout (diagnostics -> stderr). Healthy == silent stdout == 0 tokens.
#
# Monitor invocation (one persistent monitor per wave; session-scoped):
#   Monitor(persistent=true, description="agent stall watchdog",
#           command='bash "${CLAUDE_SKILL_DIR}/../../scripts/agent-watchdog.sh" --session-id ${CLAUDE_SESSION_ID} --stall-secs 300')
#   Use the portable plugin-root path -- grand-admiral resolves ${CLAUDE_SKILL_DIR}
#   at skill-load time; a bare relative `scripts/...` fails because the Monitor's
#   CWD is the user's repo, not the plugin root.
#
# MULTI-SESSION SEPARATION (a shared host runs many concurrent sessions, each with
# its own ~/.claude/teams/session-<id> team). Bind the watchdog to THIS session's
# team so it never monitors a neighbour's agents. Team-selection precedence:
#   --team-dir <path>  (explicit, wins) > --session-id <id> > $CLAUDE_SESSION_ID
#   env (inherited by the Monitor process) > newest-by-mtime autodetect.
# --session-id matches the team whose dir is session-<id> OR whose leadSessionId
# equals/prefix-matches <id> (dir suffix is the first 8 hex of the full UUID, so
# the match is prefix-tolerant either way). EVERY downstream lookup -- members,
# tmux panes, transcripts, worktrees, tasks -- is scoped to that ONE team. When no
# binding is given and >1 candidate team exists, autodetect emits a one-time stderr
# WARNING naming the chosen session so silent mis-binding becomes visible.
#
# CRITICAL -- a STALL line is a PRE-FILTER, never an auto-kill trigger
#   It prompts the coordinator to INVESTIGATE (read the transcript,
#   `git -C <cwd> status/diff`, confirm no build), THEN decide. Recovery
#   doctrine: grand-admiral skill.
#
# Three discovery sources (dedup by canonical label; team entry wins)
#   SOURCE A -- TEAM members (NAMED, task-gated): the SESSION-SELECTED
#     ~/.claude/teams/session-*/config.json members with isActive==true AND
#     agentType != "team-lead". Canonical label = member `name`. Shared-cwd members
#     (which used to be skipped) are now clocked by transcript mtime, and tmux-
#     backed members additionally get process-liveness / GONE coverage.
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
#   --session-id   ID   bind to THIS session's team (dir session-<ID> or matching
#                       leadSessionId). Defaults to $CLAUDE_SESSION_ID. Precedence:
#                       --team-dir > --session-id > $CLAUDE_SESSION_ID > autodetect.
#   --team-dir     DIR  team session dir w/ config.json (explicit path, wins over
#                       --session-id; default: session-selected, else newest dir)
#   --tasks-dir    DIR  task store (default: ~/.claude/tasks/<teamName> from the
#                       config `name`; fallback newest ~/.claude/tasks/session-*)
#   --projects-dir DIR  projects base for subagent transcripts
#                       (default: ~/.claude/projects)
#   --worktrees    DIR  worktree root holding agent-* dirs (default
#                       .claude/worktrees, resolved against the team root)
#   --watch-subagents   enable best-effort background-subagent monitoring (off)
#   --no-gone           disable tmux process-liveness / GONE detection (on)
#   --gone-polls   N    consecutive signalless polls before an agent is        (default: 2)
#                       declared gone (tolerates transient config/find misses);
#                       ALSO the consecutive confirmations a GONE event needs
#   --stall-secs   N    idle seconds (>=) before STALL             (default: 300)
#   --resume-secs  N    idle seconds (<) to declare RESUMED; must  (default: 60)
#                       be < --stall-secs
#   --poll-secs    N    seconds between polls                      (default: 45)
#
# Output (ONLY these line shapes ever reach stdout)
#   STALL agent=<name> idle=<N>s reason=owns-in_progress-idle   (named: A, C)
#   STALL agent=<key>  idle=<N>s reason=subagent-idle           (anonymous: B)
#   GONE  agent=<name> reason=pane-dead|pid-gone|stale-active   (named: A, tmux)
#   RESUMED agent=<key> idle=<N>s          (clock back under --resume-secs / lost work)
#   RESUMED agent=<key> reason=gone        (pruned: signalless for --gone-polls)
#   RESUMED agent=<name> reason=recovered  (a GONE pane shows a live command again)
#
# Exit: runs forever; transient stat/find/proc/python3 failures are swallowed
# (|| true) so a momentary hiccup never kills the loop.

set -euo pipefail

# ---- defaults -------------------------------------------------------------
team_dir=""
session_id=""
tasks_dir=""
projects_dir="$HOME/.claude/projects"
worktrees_dir=".claude/worktrees"
watch_subagents=0
gone_detect=1
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
Usage: agent-watchdog.sh [--session-id ID] [--team-dir DIR] [--tasks-dir DIR]
                         [--projects-dir DIR] [--worktrees DIR] [--watch-subagents]
                         [--no-gone] [--gone-polls N] [--stall-secs N]
                         [--resume-secs N] [--poll-secs N]
STALL = owns an in_progress task AND idle >= threshold AND no build under the
agent's worktree/cwd. An idle agent owning no in_progress task is never flagged.
--session-id (default $CLAUDE_SESSION_ID) scopes ALL discovery to THIS session's
team; precedence --team-dir > --session-id > $CLAUDE_SESSION_ID > newest autodetect.
Emits ONLY 'STALL'/'RESUMED' transition lines to stdout; diagnostics to stderr.
USAGE
}

newest_mtime_under() {            # newest mtime of ANY entry under $1 (incl. build dirs)
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -printf '%T@\n' 2>/dev/null | awk '{v=$0+0; if(NR==1||v>x){x=v; s=$0}} END{if(NR)print s}' || true)"
  printf '%s' "${m%.*}"
}

newest_mtime_cwd() {              # like above but pruning .git (shared-repo noise)
  local dir="$1" m
  [ -d "$dir" ] || return 0
  m="$(find "$dir" -name .git -prune -o -printf '%T@\n' 2>/dev/null | awk '{v=$0+0; if(NR==1||v>x){x=v; s=$0}} END{if(NR)print s}' || true)"
  printf '%s' "${m%.*}"
}

newest_path_in() {
  local dir="$1"; shift
  [ -d "$dir" ] || return 0
  find "$dir" "$@" -printf '%T@\t%p\n' 2>/dev/null \
    | awk -F'\t' '{v=$1+0; if(NR==1||v>x){x=v; p=substr($0,index($0,"\t")+1)}} END{if(NR)print p}' || true
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
    if m.get("agentType") == "team-lead":
        lc = m.get("cwd") or ""            # lead's cwd: a de-isolated agent may land here
        if lc:
            print("LEADCWD\t" + lc)
        lp = m.get("tmuxPaneId") or ""     # seed lead pane for the wrong-server guard
        if lp:
            print("LEADPANE\t" + lp)
        continue
    if m.get("isActive") is True:
        n = m.get("name") or ""
        if n:
            # name, cwd, agentId, agentType, tmuxPaneId, backendType (tab-joined)
            print("\t".join([
                "MEMBER", n, m.get("cwd") or "", m.get("agentId") or "",
                m.get("agentType") or "", m.get("tmuxPaneId") or "",
                m.get("backendType") or ""]))
PY
}

select_team() {
  # Pick THE one team dir for this session and report the leadSessionIds of every
  # OTHER team (so transcript matching can refuse foreign artifacts). Precedence:
  #   explicit --team-dir ($2) > --session-id/$CLAUDE_SESSION_ID ($3) > newest mtime.
  # Output (tab-kv): MODE explicit|matched|autodetect|none, DIR, LEAD, CANDIDATES,
  # OTHERLEAD* (one per non-selected team).
  python3 - "$1" "$2" "$3" <<'PY' 2>/dev/null || true
import json, os, sys, glob
teams, team_dir_arg, want = sys.argv[1], sys.argv[2], sys.argv[3]

def lead_of(d):
    try:
        return json.load(open(os.path.join(d, "config.json"))).get("leadSessionId") or ""
    except Exception:
        return ""

def mtime(d):
    try:
        return os.stat(d).st_mtime
    except Exception:
        return 0.0

# A real team dir holds a config.json; bare placeholders never count as candidates.
cands = [d for d in glob.glob(os.path.join(teams, "session-*"))
         if os.path.isfile(os.path.join(d, "config.json"))]

def emit(mode, sel):
    print("MODE\t" + mode)
    print("CANDIDATES\t%d" % len(cands))
    if sel:
        print("DIR\t" + sel)
        print("LEAD\t" + lead_of(sel))
    rsel = os.path.realpath(sel) if sel else ""
    for d in cands:                                    # every team that is NOT ours
        if os.path.realpath(d) == rsel:
            continue
        l = lead_of(d)
        if l:
            print("OTHERLEAD\t" + l)

if team_dir_arg:                                       # explicit path wins outright
    emit("explicit", team_dir_arg)
elif want:                                             # bind to the invoking session only
    sel = None
    for d in cands:                                    # 1) dir suffix session-<id> (prefix-tolerant)
        suf = os.path.basename(d)[len("session-"):]
        if suf and (suf == want or want.startswith(suf) or suf.startswith(want)):
            sel = d
            break
    if sel is None:                                    # 2) leadSessionId equals/prefix of <id>
        for d in cands:
            l = lead_of(d)
            if l and (l == want or want.startswith(l) or l.startswith(want)):
                sel = d
                break
    emit("matched" if sel else "none", sel)
elif cands:                                            # autodetect: newest config.json by mtime
    emit("autodetect", max(cands, key=mtime))
else:
    emit("none", None)
PY
}

member_transcripts() {   # map shared-cwd members -> own transcript jsonl (turn-mtime clock)
  python3 - "$1" "$2" "$3" "$4" <<'PY' 2>/dev/null || true
import json, sys, os, glob, re, collections
cfg, projects, lead_session = sys.argv[1], sys.argv[2], sys.argv[3]
other_leads = set(filter(None, (sys.argv[4] if len(sys.argv) > 4 else "").split(",")))
try:
    c = json.load(open(cfg))
except Exception:
    sys.exit(0)

def to_secs(v):                                  # createdAt may be ms epoch / iso / num
    try: v = float(v)
    except Exception: return 0.0
    return v / 1000.0 if v > 1e11 else v
created_s = to_secs(c.get("createdAt") or 0)

members, typecount = [], collections.Counter()
for m in c.get("members", []):
    if m.get("agentType") == "team-lead" or m.get("isActive") is not True:
        continue
    n = m.get("name") or ""
    if not n:
        continue
    members.append((n, m.get("agentId") or "", m.get("agentType") or "", m.get("cwd") or ""))
    if m.get("agentType"):
        typecount[m.get("agentType")] += 1
if not members:
    sys.exit(0)

def first_agentid(f):                            # subagent transcript: agentId is near the top
    try:
        with open(f, errors="ignore") as fh:
            for _ in range(40):
                ln = fh.readline()
                if not ln:
                    break
                try: o = json.loads(ln)
                except Exception: continue
                if o.get("agentId"):
                    return o["agentId"]
    except Exception:
        return None
    return None

def meta_agenttype(f):                           # sibling agent-*.meta.json names the agentType
    try:
        return json.load(open(f[:-len(".jsonl")] + ".meta.json")).get("agentType") or None
    except Exception:
        return None

# Subagent transcripts live UNDER this team's leadSession dir, so they are
# session-scoped by construction -- no foreign artifact can reach them. byid is the
# exact internal-agentId map; sub_by_type lets a member with a unique agentType bind
# to its newest subagent transcript even when the config agentId is an external label.
byid = {}                                        # internal agentId -> subagent transcript
sub_by_type = collections.defaultdict(list)      # agentType -> [(mtime, path)] (this team only)
if lead_session:
    for sd in glob.glob(os.path.join(projects, "*", lead_session, "subagents")):
        for f in glob.glob(os.path.join(sd, "agent-*.jsonl")):
            try: mt = os.stat(f).st_mtime
            except Exception: continue
            aid = first_agentid(f)
            if aid:
                byid.setdefault(aid, f)
            at = meta_agenttype(f)
            if at:
                sub_by_type[at].append((mt, f))

def first_agent_setting(f):                      # agent-setting record sits near the top
    try:
        with open(f, errors="ignore") as fh:
            for _ in range(12):
                ln = fh.readline()
                if not ln:
                    break
                try: o = json.loads(ln)
                except Exception: continue
                if o.get("type") == "agent-setting":
                    return o.get("agentSetting"), o.get("sessionId")
    except Exception:
        return None, None
    return None, None

def slug_dirs(cwd):                              # tolerate either project-dir encoding
    c = cwd.rstrip("/")
    dirs = []
    for pat in (r"[^A-Za-z0-9-]", r"[/.]"):
        d = os.path.join(projects, re.sub(pat, "-", c))
        if d not in dirs and os.path.isdir(d):
            dirs.append(d)
    return dirs

slug_cache = {}                                  # cwd -> {agentType: [(mtime, path)]}
def by_type_for(cwd):
    if cwd in slug_cache:
        return slug_cache[cwd]
    out = collections.defaultdict(list)
    for sdir in slug_dirs(cwd):
        for f in glob.glob(os.path.join(sdir, "*.jsonl")):
            try: st = os.stat(f)
            except Exception: continue
            if created_s and st.st_mtime < created_s - 5:   # predates this team session
                continue
            at, sid = first_agent_setting(f)
            if not at or not sid:
                continue
            if lead_session and sid == lead_session:
                continue                         # skip THIS team's own lead transcript
            if sid in other_leads:
                continue                         # belongs to ANOTHER session's team -> never trust
            out[at].append((st.st_mtime, f, sid))
    slug_cache[cwd] = out
    return out

for n, aid, at, cwd in members:
    path = None
    if aid and aid in byid:                       # exact internal-agentId match (session-scoped)
        path = byid[aid]
    elif at and typecount[at] == 1 and at in sub_by_type:   # session-scoped subagent transcript
        path = max(sub_by_type[at])[1]            # newest subagent of this unique agentType
    elif at and typecount[at] == 1 and cwd:       # slug fallback (the only cross-session-prone path)
        cand = by_type_for(cwd).get(at) or []
        sids = {c[2] for c in cand}
        if len(sids) == 1:                        # one session owns this type in the cwd -> trust newest
            path = max(cand)[1]
        # >1 distinct session of this agentType share the cwd: cannot attribute to
        # THIS team from disk -> skip rather than clock a neighbour's transcript.
    if path:
        print("TS\t" + n + "\t" + path)
PY
}

is_bare_shell() {   # pane_current_command of a pane whose claude/node process exited
  case "$1" in
    sh|-sh|bash|-bash|zsh|-zsh|dash|-dash|ksh|-ksh|fish|-fish|login|cd) return 0 ;;
  esac
  return 1
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

build_simple() {   # basename that means "build" on its own (incl. gradlew/mvnw wrappers)
  case "$1" in
    rustc|cc1|cc1plus|gcc|g++|clang|clang++|ld|make|cmake|ninja|gradle|gradlew|mvn|mvnw|bazel|tsc|webpack|pytest|jest) return 0 ;;
  esac
  return 1
}
build_subcmd() {   # $1=program basename, $2=subcommand
  case "$1" in
    cargo)    case "$2" in build|test|check|clippy|run) return 0 ;; esac ;;
    go)       case "$2" in build|test|run) return 0 ;; esac ;;
    dotnet)   case "$2" in build|test|run) return 0 ;; esac ;;
    pip|pip3) [ "$2" = install ] && return 0 ;;
  esac
  return 1
}
bn() { local s="$1"; printf '%s' "${s##*/}"; }   # basename

is_build_proc() {
  # True if pid $1's argv is an anchored build/test command -- matched directly
  # on argv0 (native ELF: cargo build, make, rustc, ...), OR through a shebang/
  # interpreter wrapper (QA-017). A script with `#!/bin/sh` (`./gradlew build`),
  # `#!/usr/bin/env bash` (`env [VAR=val…] [-flags] bash ./mvnw …`), or a console
  # entry point (`python3 .../pytest`, `node .../jest`) presents argv0 as the
  # interpreter, so the real tool is in a later argv -- peel one interpreter
  # layer (skipping env's VAR=val / -flag prefix) and test that token's basename.
  local cmd="/proc/$1/cmdline" tok i n c
  [ -r "$cmd" ] || return 1
  local -a argv=()
  while IFS= read -r -d '' tok; do argv+=("$tok"); done < "$cmd" 2>/dev/null || true
  n="${#argv[@]}"; [ "$n" -gt 0 ] || return 1

  i=0
  if [ "$(bn "${argv[0]}")" = env ]; then           # env: skip VAR=val and -flag prefix
    i=1
    while [ "$i" -lt "$n" ]; do
      case "${argv[$i]}" in -*|*=*) i=$((i + 1)) ;; *) break ;; esac
    done
  fi
  [ "$i" -lt "$n" ] || return 1

  c="$(bn "${argv[$i]}")"
  case "$c" in                                      # peel one interpreter -> next token is the tool/script
    sh|bash|dash|zsh|ksh|perl|ruby|node|nodejs) i=$((i + 1)) ;;
    python|python2|python3)
      if [ "${argv[$((i + 1))]:-}" = "-m" ]; then   # python -m pytest / -m pip install
        case "$(bn "${argv[$((i + 2))]:-}")" in
          pytest|build) return 0 ;;
          pip) [ "$(bn "${argv[$((i + 3))]:-}")" = install ] && return 0 ;;
        esac
        return 1
      fi
      i=$((i + 1)) ;;
  esac
  [ "$i" -lt "$n" ] || return 1

  build_simple "$(bn "${argv[$i]}")" && return 0
  build_subcmd "$(bn "${argv[$i]}")" "$(bn "${argv[$((i + 1))]:-}")" && return 0
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

declare -A STATE      # canonical key -> OK | STALLED | GONE (persists across polls)
declare -A OWNERS     # owner name -> 1 (rebuilt each poll)
declare -A WARNED     # one-time stderr notes already emitted
declare -A MISS       # key -> consecutive polls with NO live signal (gone grace)
declare -A ALIVE      # key -> 1 if it produced an evaluable signal THIS poll
declare -A GONE_HITS  # key -> consecutive polls a GONE candidate held (confirmation)
declare -A PANE_CMD   # tmux pane id -> pane_current_command (rebuilt each poll)

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

classify_pane() {
  # $1=tmuxPaneId  $2=backendType -> sets PANE_STATE to alive|dead|missing|unknown.
  # unknown == "can't tell" (no tmux, server unreachable, non-tmux backend, or a
  # wrong-socket server where none of our panes resolve) -> NEVER drives GONE.
  PANE_STATE=unknown
  [ "$gone_detect" -eq 1 ] && [ "$have_tmux" -eq 1 ] && [ "$tmux_reachable" -eq 1 ] || return 0
  local paneid="$1" bt="$2"
  [ "$bt" = tmux ] || return 0
  case "$paneid" in %*) ;; *) return 0 ;; esac
  if [ -n "${PANE_CMD[$paneid]+x}" ]; then
    if is_bare_shell "${PANE_CMD[$paneid]}"; then PANE_STATE=dead; else PANE_STATE=alive; fi
  elif [ "$any_sibling" -eq 1 ]; then            # pane absent in a server proven to hold our panes
    PANE_STATE=missing
  fi
}

gone_eval() {
  # $1=key  $2=pane state (dead|missing)  $3=activity epoch (may be empty).
  # Edge-triggered GONE after --gone-polls consecutive confirmations; a
  # process-absent signal corroborated by a stale clock is the strongest case.
  local key="$1" pst="$2" act_e="$3" reason idle=-1
  [[ "$act_e" =~ ^[0-9]+$ ]] && idle=$(( now - act_e ))
  if [ "$idle" -ge 0 ] && [ "$idle" -ge "$stall_secs" ]; then
    reason="stale-active"
  elif [ "$pst" = dead ]; then
    reason="pane-dead"
  else
    reason="pid-gone"
  fi
  GONE_HITS["$key"]=$(( ${GONE_HITS[$key]:-0} + 1 ))
  if [ "${GONE_HITS[$key]}" -ge "$gone_polls" ] && [ "${STATE[$key]:-OK}" != "GONE" ]; then
    STATE["$key"]="GONE"
    printf 'GONE agent=%s reason=%s\n' "$key" "$reason"
  fi
}

gone_recover() {   # pane verifiably ALIVE again -> reset confirmation, clear any GONE
  local key="$1"
  GONE_HITS["$key"]=0
  if [ "${STATE[$key]:-OK}" = "GONE" ]; then
    STATE["$key"]="OK"
    printf 'RESUMED agent=%s reason=recovered\n' "$key"
  fi
}

gone_reset() { GONE_HITS["$1"]=0; }   # liveness unknown this poll -> stop counting, keep state

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
    --session-id)     [ $# -ge 2 ] || die "--session-id needs a value";   session_id="$2";   shift 2 ;;
    --tasks-dir)      [ $# -ge 2 ] || die "--tasks-dir needs a value";    tasks_dir="$2";    shift 2 ;;
    --projects-dir)   [ $# -ge 2 ] || die "--projects-dir needs a value"; projects_dir="$2"; shift 2 ;;
    --worktrees)      [ $# -ge 2 ] || die "--worktrees needs a value";    worktrees_dir="$2"; shift 2 ;;
    --watch-subagents) watch_subagents=1; shift ;;
    --no-gone)        gone_detect=0; shift ;;
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

# Default the session binding from the inherited env (the Monitor process carries
# $CLAUDE_SESSION_ID). --session-id overrides it; --team-dir overrides both.
[ -n "$session_id" ] || session_id="${CLAUDE_SESSION_ID:-}"

command -v python3 >/dev/null 2>&1 || die "python3 not found (required to read team config + task store)"
# GNU find/stat probe -- the mtime clocks are GNU-only; fail loud, not silent.
stat -c %Y "$0" >/dev/null 2>&1 || die "GNU stat (stat -c %Y) required"
find "$0" -maxdepth 0 -printf '' >/dev/null 2>&1 || die "GNU find (find -printf) required"

# tmux is OPTIONAL: process-liveness / GONE just stays off when it is absent.
have_tmux=0
[ "$gone_detect" -eq 1 ] && command -v tmux >/dev/null 2>&1 && have_tmux=1

printf 'agent-watchdog: poll=%ss stall=%ss resume=%ss gone-polls=%s gone-detect=%s tmux=%s session=%s team-dir=%s tasks-dir=%s worktrees=%s watch-subagents=%s\n' \
  "$poll_secs" "$stall_secs" "$resume_secs" "$gone_polls" "$gone_detect" "$have_tmux" "${session_id:-<auto>}" "${team_dir:-<auto>}" "${tasks_dir:-<auto>}" "$worktrees_dir" "$watch_subagents" >&2

# ---- main loop ------------------------------------------------------------
while :; do
  now="$(date +%s 2>/dev/null || true)"
  if ! [[ "$now" =~ ^[0-9]+$ ]]; then
    sleep "$poll_secs" || true
    continue
  fi

  # ---- select THE team for this session (precedence: --team-dir > --session-id /
  #      $CLAUDE_SESSION_ID > newest-mtime autodetect). other_leads collects every
  #      OTHER team's leadSessionId so transcript matching can refuse foreign work. ----
  sel_mode=""; td=""; sel_lead=""; sel_cands=0; other_leads=()
  while IFS=$'\t' read -r kind val; do
    case "$kind" in
      MODE)       sel_mode="$val" ;;
      DIR)        td="$val" ;;
      LEAD)       sel_lead="$val" ;;
      CANDIDATES) sel_cands="$val" ;;
      OTHERLEAD)  [ -n "$val" ] && other_leads+=("$val") ;;
    esac
  done < <(select_team "$HOME/.claude/teams" "$team_dir" "$session_id")
  [[ "$sel_cands" =~ ^[0-9]+$ ]] || sel_cands=0

  if [ "$sel_mode" = autodetect ] && [ "$sel_cands" -gt 1 ] && [ -n "$td" ]; then
    warn_once "autodetect:${td##*/}" "ambiguous team autodetect: $sel_cands candidate team dirs on this host; bound to ${td##*/} (leadSessionId=${sel_lead:-?}) by NEWEST mtime — this may be ANOTHER session's team. Pass --session-id \$CLAUDE_SESSION_ID (or --team-dir) to track THIS session's team."
  elif { [ "$sel_mode" = matched ] || [ "$sel_mode" = explicit ]; } && [ -n "$td" ]; then
    warn_once "bind:${td##*/}" "session-scoped to ${td##*/} (leadSessionId=${sel_lead:-?}, mode=$sel_mode)"
  fi
  other_leads_csv=""
  [ "${#other_leads[@]}" -gt 0 ] && other_leads_csv="$(IFS=,; printf '%s' "${other_leads[*]}")"

  # ---- parse team config ----
  team_present=0; team_name=""; lead_session=""; lead_cwd=""; lead_pane=""
  m_names=(); m_cwds=(); m_aids=(); m_types=(); m_panes=(); m_btypes=()
  if [ -n "$td" ] && [ -f "$td/config.json" ]; then
    team_present=1
    while IFS=$'\t' read -r kind a b c d e f; do
      case "$kind" in
        NAME)     team_name="$a" ;;
        LEAD)     lead_session="$a" ;;
        LEADCWD)  lead_cwd="$a" ;;
        LEADPANE) lead_pane="$a" ;;
        MEMBER)   m_names+=("$a"); m_cwds+=("$b"); m_aids+=("$c")
                  m_types+=("$d"); m_panes+=("$e"); m_btypes+=("$f") ;;
      esac
    done < <(parse_team "$td/config.json")
    if [ "${#m_names[@]}" -eq 0 ] && [ -z "$lead_session" ]; then
      warn_once "cfgparse:$td" "team config at $td unreadable/partial; Source A empty this poll"
    fi
  fi

  # ---- resolve task store + OWNERS_WITH_WORK ----
  # When bound to a team (team_name known) use ONLY that team's task dir; never the
  # newest-session fallback, which would import a stranger's owners. The newest
  # fallback applies solely to the fully-unbound case (no team AND no session id).
  tkdir="$tasks_dir"
  if [ -z "$tkdir" ]; then
    if [ -n "$team_name" ]; then
      [ -d "$HOME/.claude/tasks/$team_name" ] && tkdir="$HOME/.claude/tasks/$team_name"
    elif [ -z "$session_id" ]; then
      tkdir="$(newest_path_in "$HOME/.claude/tasks" -maxdepth 1 -type d -name 'session-*')"
    fi
  fi
  unset OWNERS; declare -A OWNERS
  if [ -n "$tkdir" ] && [ -d "$tkdir" ]; then
    while IFS= read -r owner; do [ -n "$owner" ] && OWNERS["$owner"]=1; done < <(build_owners "$tkdir")
  fi

  # ---- resolve worktrees root (default relative -> the lead's repo, where
  #      worktrees live). Fall back to a member cwd only when the lead cwd is
  #      unknown: a member may itself be running inside its own worktree, so its
  #      cwd is a wrong base for <cwd>/.claude/worktrees and breaks discovery. ----
  wt_dir="$worktrees_dir"
  case "$wt_dir" in
    /*) : ;;
    *)
      wt_base="$lead_cwd"; [ -n "$wt_base" ] || wt_base="${m_cwds[0]:-}"
      [ -n "$wt_base" ] && wt_dir="${wt_base%/}/$worktrees_dir" ;;
  esac

  # ---- count active-member cwds (shared-cwd detection) ----
  # Seed the lead's cwd as an occupant: a de-isolated agent that lands in the
  # lead's repo dir then shares it (count >=2), so it is flagged non-isolatable
  # instead of being mis-monitored via the lead's own (noisy) file activity.
  unset CWD_COUNT; declare -A CWD_COUNT
  if [ "$team_present" -eq 1 ]; then
    [ -n "$lead_cwd" ] && CWD_COUNT["$lead_cwd"]=$(( ${CWD_COUNT[$lead_cwd]:-0} + 1 ))
    for i in "${!m_names[@]}"; do
      c="${m_cwds[$i]}"; [ -n "$c" ] && CWD_COUNT["$c"]=$(( ${CWD_COUNT[$c]:-0} + 1 ))
    done
  fi

  # ---- tmux pane snapshot (process-liveness / GONE) ----
  # One list-panes call per poll feeds PANE_CMD. tmux_reachable distinguishes "no
  # server" from "server up". any_sibling guards a wrong-socket server: only trust
  # a MISSING pane as GONE when >=1 of OUR configured panes resolves here.
  unset PANE_CMD; declare -A PANE_CMD
  tmux_reachable=0; any_sibling=0
  if [ "$gone_detect" -eq 1 ] && [ "$have_tmux" -eq 1 ]; then
    while IFS=$'\t' read -r pn cmd; do
      [ -n "$pn" ] || continue
      PANE_CMD["$pn"]="$cmd"; tmux_reachable=1
    done < <(tmux list-panes -a -F $'#{pane_id}\t#{pane_current_command}' 2>/dev/null || true)
    if [ "$tmux_reachable" -eq 1 ]; then
      { [ -n "$lead_pane" ] && [ -n "${PANE_CMD[$lead_pane]+x}" ]; } && any_sibling=1
      if [ "$any_sibling" -eq 0 ]; then
        for pn in "${m_panes[@]:-}"; do
          [ -n "$pn" ] && [ -n "${PANE_CMD[$pn]+x}" ] && { any_sibling=1; break; }
        done
      fi
    fi
  fi

  # ---- transcript-mtime fallback map (shared-cwd members only) ----
  # Resolve once per poll, and only when at least one active member lacks a
  # worktree (the case where worktree/cwd mtime cannot isolate its activity).
  unset TS_MAP; declare -A TS_MAP
  if [ "$team_present" -eq 1 ] && [ -n "$td" ] && [ -f "$td/config.json" ]; then
    need_ts=0
    for i in "${!m_names[@]}"; do
      [ -d "$wt_dir/agent-$(canon "${m_names[$i]}")" ] || { need_ts=1; break; }
    done
    if [ "$need_ts" -eq 1 ]; then
      while IFS=$'\t' read -r tag nm pth; do
        [ "$tag" = TS ] && [ -n "$nm" ] && [ -n "$pth" ] && TS_MAP["$(canon "$nm")"]="$pth"
      done < <(member_transcripts "$td/config.json" "$projects_dir" "$lead_session" "$other_leads_csv")
    fi
  fi

  unset SEEN ALIVE; declare -A SEEN ALIVE   # SEEN = dedup (claimed only on a real signal); ALIVE = had a live signal

  # ---- SOURCE A: team members (NAMED, gated) ----
  # SEEN is claimed ONLY after a real activity signal exists (QA-016): an active
  # member with no signal must NOT block the gone-prune, or a removed-worktree
  # member would stay STALLED forever.
  if [ "$team_present" -eq 1 ]; then
    for i in "${!m_names[@]}"; do
      name="${m_names[$i]}"; cwd="${m_cwds[$i]}"
      paneid="${m_panes[$i]:-}"; btype="${m_btypes[$i]:-}"
      [ -n "$name" ] || continue
      key="$(canon "$name")"
      [ -n "${SEEN[$key]:-}" ] && continue

      # --- activity clock: worktree -> own cwd -> transcript-mtime fallback ---
      a_dir=""; a_mt=""
      wt="$wt_dir/agent-$key"
      if [ -d "$wt" ]; then
        a_dir="$wt"; a_mt="$(newest_mtime_under "$wt")"
      elif [ -n "$cwd" ] && [ "${CWD_COUNT[$cwd]:-0}" -ge 2 ]; then
        tpath="${TS_MAP[$key]:-}"
        if [ -n "$tpath" ] && [ -e "$tpath" ]; then
          a_dir="$cwd"; a_mt="$(stat -c %Y "$tpath" 2>/dev/null || true)"   # transcript turn-mtime
        else
          warn_once "sharedcwd:$key" "no per-agent file signal for $key (cwd shared with the team-lead or another member, so its mtime is polluted) and no transcript resolved — give it an isolated worktree to monitor"
        fi
      elif [ -n "$cwd" ]; then
        a_dir="$cwd"; a_mt="$(newest_mtime_cwd "$cwd")"
      fi

      # --- process liveness (tmux pane) -> GONE supersedes STALL ---
      classify_pane "$paneid" "$btype"
      case "$PANE_STATE" in
        dead|missing)                       # process verifiably ABSENT
          SEEN["$key"]=1; ALIVE["$key"]=1   # we are managing it via the GONE machine
          gone_eval "$key" "$PANE_STATE" "$a_mt"
          continue ;;
        alive)
          gone_recover "$key" ;;            # positively alive -> clear any prior GONE
        *)
          gone_reset "$key" ;;              # unknown -> stop counting, keep state
      esac

      if [ "$PANE_STATE" = alive ] && [ -z "$a_mt" ]; then
        SEEN["$key"]=1; ALIVE["$key"]=1     # alive but no usable clock: liveness still proven
        continue
      fi
      [ -n "$a_mt" ] || continue            # no signal -> don't claim SEEN; gone-prune may clear it
      SEEN["$key"]=1
      evaluate_named "$key" "$a_mt" "$a_dir"
    done
  fi

  # ---- SOURCE C: worktree-isolated agents (NAMED, gated) ----
  if [ -n "$wt_dir" ] && [ -d "$wt_dir" ]; then
    for d in "$wt_dir"/agent-*; do
      [ -d "$d" ] || continue
      key="$(canon "${d##*/}")"
      [ -n "${SEEN[$key]:-}" ] && continue
      a_mt="$(newest_mtime_under "$d")"
      [ -n "$a_mt" ] || continue
      SEEN["$key"]=1
      evaluate_named "$key" "$a_mt" "$d"
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
    elif [ -z "$session_id" ]; then
      # fully unbound (no team AND no session id) -> enumerate ALL subagents dirs in
      # newest slug. Suppressed when session-bound: a stranger's slug is not ours.
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
        m="$(stat -c %Y "$f" 2>/dev/null || true)"
        [ -n "$m" ] || continue          # no signal -> don't claim SEEN
        SEEN["$key"]=1
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
      # STALLED -> announce the clear; a confirmed-GONE key was already announced,
      # so drop it silently (no duplicate). Either way, forget all per-key state.
      [ "${STATE[$key]}" = "STALLED" ] && printf 'RESUMED agent=%s reason=gone\n' "$key"
      unset 'STATE[$key]' 'MISS[$key]' 'GONE_HITS[$key]'
    fi
  done

  sleep "$poll_secs" || true
done
