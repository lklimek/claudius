#!/usr/bin/env bash
# Integration test: agent-watchdog GONE detection over per-session tmux swarm sockets.
#
# Proves the swarm-socket discovery fix end-to-end against REAL tmux servers:
#   T1  the correct socket is chosen among >=2 sibling claude-swarm-* sockets
#   T2  pane-id collision (%0/%1 reused per socket) does NOT cause a cross-session
#       misread -- a neighbour's LIVE %1 cannot mask our DEAD %1
#   T3  no matching socket  -> GONE stays a no-op + one-time stderr idle note
#   T4  a dead/bare-shell pane on OUR socket drives GONE through the gone-polls gate
#
# tmux is required; the test skips (rc 0) when tmux is unavailable. Fully isolated:
# HOME + TMUX_TMPDIR point at a private mktemp tree, $TMUX is unset (the prod case).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WATCHDOG="${WATCHDOG:-$SCRIPT_DIR/../scripts/agent-watchdog.sh}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
pass=0; fail=0
ok()   { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad()  { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }
expect() {   # $1=desc  $2=ERE pattern  $3=file : pass when pattern is PRESENT
  if grep -Eq "$2" "$3"; then ok "$1"; else bad "$1 (got: $(tr '\n' '|' < "$3"))"; fi
}
refute() {   # $1=desc  $2=ERE pattern  $3=file : pass when pattern is ABSENT
  if grep -Eq "$2" "$3"; then bad "$1 (got: $(tr '\n' '|' < "$3"))"; else ok "$1"; fi
}

if ! command -v tmux >/dev/null 2>&1; then
  echo -e "${YEL}SKIP${NC} tmux not installed; cannot exercise swarm-socket discovery"
  exit 0
fi

# Unix socket paths cap at ~108 bytes, so the tmux dir MUST be short -> /tmp, not the
# (long) scratchpad. HOME holds only regular files, so its length is irrelevant.
BASE="$(mktemp -d /tmp/wd-gone-XXXXXX)"
export HOME="$BASE/home"
export TMUX_TMPDIR="$BASE/tt"
unset TMUX
mkdir -p "$HOME/.claude/teams" "$HOME/.claude/tasks" "$HOME/.claude/projects" \
         "$BASE/wt" "$TMUX_TMPDIR" \
         "$BASE/cwd-lead" "$BASE/cwd-bilby" "$BASE/cwd-smythe" "$BASE/cwd-ghost"
: > "$BASE/cwd-bilby/work.txt"; : > "$BASE/cwd-smythe/work.txt"; : > "$BASE/cwd-ghost/work.txt"

OUR="$TMUX_TMPDIR/claude-swarm-1111"        # this session's socket
NB="$TMUX_TMPDIR/claude-swarm-2222"         # a neighbour session's socket (collides on %0/%1)

cleanup() {
  [ -n "${WPID:-}" ] && kill "$WPID" 2>/dev/null
  tmux -S "$OUR" kill-server 2>/dev/null
  tmux -S "$NB"  kill-server 2>/dev/null
  rm -rf "$BASE"
}
trap cleanup EXIT

# OUR socket: %0 bilby ALIVE (sleep), %1 smythe DEAD (bare shell). Titles carry the
# agentType (persist independently of the running command) so binding works even for
# the dead pane.
tmux -S "$OUR" new-session -d -s ours -x 200 -y 50 'sleep 1000000'
tmux -S "$OUR" split-window -d -t ours 'exec bash'
tmux -S "$OUR" select-pane -t %0 -T 'claudius:developer-bilby'
tmux -S "$OUR" select-pane -t %1 -T 'claudius:security-engineer-smythe'

# NEIGHBOUR socket: SAME pane ids (%0/%1), DIFFERENT agentTypes, and crucially %1 is
# ALIVE here. If discovery ever read this socket for our %1, smythe would look alive
# and never go GONE -- so a GONE for smythe positively proves we read OUR socket.
tmux -S "$NB" new-session -d -s nb -x 200 -y 50 'sleep 1000000'
tmux -S "$NB" split-window -d -t nb 'sleep 1000000'
tmux -S "$NB" select-pane -t %0 -T 'claudius:developer-other'
tmux -S "$NB" select-pane -t %1 -T 'claudius:reviewer-other'

write_team() {   # $1=session-suffix  $2=member-json
  local dir="$HOME/.claude/teams/session-$1"
  mkdir -p "$dir"
  cat > "$dir/config.json" <<JSON
{
  "name": "session-$1",
  "leadSessionId": "lead-$1",
  "createdAt": $(date +%s),
  "members": [
    {"agentType": "team-lead", "name": "lead", "cwd": "$BASE/cwd-lead", "isActive": true},
    $2
  ]
}
JSON
  printf '%s' "$dir"
}

run_watchdog() {   # $1=team-dir  $2=seconds-to-observe  -> sets OUT/ERR globals
  OUT="$BASE/out.$RANDOM"; ERR="$BASE/err.$RANDOM"
  bash "$WATCHDOG" --team-dir "$1" --worktrees "$BASE/wt" \
       --tasks-dir "$HOME/.claude/tasks" --projects-dir "$HOME/.claude/projects" \
       --poll-secs 1 --gone-polls 2 --resume-secs 30 --stall-secs 300 \
       >"$OUT" 2>"$ERR" &
  WPID=$!
  sleep "$2"
  kill "$WPID" 2>/dev/null; wait "$WPID" 2>/dev/null; WPID=""
}

# === Scenario 1: matching socket among siblings, dead pane drives GONE ===
echo "=== match + GONE (T1, T2, T4) ==="
TD1="$(write_team test1 \
  '{"agentType":"claudius:developer-bilby","name":"bilby","cwd":"'"$BASE"'/cwd-bilby","agentId":"aid-bilby","tmuxPaneId":"%0","backendType":"tmux","isActive":true},
    {"agentType":"claudius:security-engineer-smythe","name":"smythe","cwd":"'"$BASE"'/cwd-smythe","agentId":"aid-smythe","tmuxPaneId":"%1","backendType":"tmux","isActive":true}')"
run_watchdog "$TD1" 5

expect "T1 bound to OUR socket (claude-swarm-1111)"        'swarm socket claude-swarm-1111' "$ERR"
refute "T1 neighbour socket claude-swarm-2222 never bound" 'claude-swarm-2222'              "$ERR"
expect "T4 dead pane on our socket drove GONE for smythe"  '^GONE agent=smythe '            "$OUT"
expect "T4 GONE reason is pane-dead"                       '^GONE agent=smythe reason=pane-dead$' "$OUT"
# smythe's %1 is DEAD on our socket but ALIVE on the neighbour's -> a GONE proves we
# read OUR %1, never the colliding neighbour %1.
refute "T2 alive pane bilby never flagged GONE (collision-safe)" '^GONE agent=bilby'        "$OUT"
refute "no spurious STALL emitted"                         '^STALL '                        "$OUT"
echo ""

# === Scenario 2: no socket carries our agentType -> GONE idle no-op (T3) ===
echo "=== no matching socket -> no-op (T3) ==="
TD2="$(write_team nomatch \
  '{"agentType":"claudius:phantom-ghost","name":"ghost","cwd":"'"$BASE"'/cwd-ghost","agentId":"aid-ghost","tmuxPaneId":"%7","backendType":"tmux","isActive":true}')"
run_watchdog "$TD2" 4

expect "T3 emitted the one-time no-matching-socket idle note" \
       'no matching tmux swarm socket for this team; GONE detection idle' "$ERR"
refute "T3 GONE stayed a no-op (sockets exist but none carry our agentType)" '^GONE ' "$OUT"
echo ""

echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
