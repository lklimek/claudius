#!/usr/bin/env bash
# Verification ledger for cargo. Usage: cargo-cached.sh <cargo args...>
#   e.g. cargo-cached.sh clippy -p my-crate --all-targets -- -D warnings
#
# Identical command + identical tree (ANY agent, ANY worktree on this machine)
# => REPLAY the recorded log + exit code (the agent gets its output at zero
# compile cost). Otherwise run the real cargo, tee the full log, and append a
# JSONL record to the ledger.
#
# FAIL-OPEN throughout: any internal error (missing jq, not a git repo, no flock)
# falls through to a plain `cargo "$@"`. Correctness of a real build always wins
# over the caching optimization.
#
# Ledger location is portable — NEVER hardcoded. A user who wants it elsewhere
# (e.g. a big disk) sets CLAUDIUS_CACHE_DIR; otherwise it follows the XDG cache.
set -uo pipefail

CACHE_ROOT="${CLAUDIUS_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/claudius}"
LEDGER_DIR="$CACHE_ROOT/ledger"
RECORDS="$LEDGER_DIR/records.jsonl"
TTL_HOURS=24

command -v jq >/dev/null 2>&1 || exec cargo "$@"
mkdir -p "$LEDGER_DIR/logs" "$LEDGER_DIR/locks" 2>/dev/null || exec cargo "$@"
git rev-parse --show-toplevel >/dev/null 2>&1 || exec cargo "$@"

# --- Cache key: everything that determines the result ----------------------
head_oid=$(git rev-parse HEAD 2>/dev/null) || exec cargo "$@"
diff_hash=$(git diff HEAD 2>/dev/null | sha256sum | cut -d' ' -f1)
# Untracked, non-ignored files: agents routinely create new source before testing.
untracked_hash=$(git ls-files --others --exclude-standard -z 2>/dev/null \
  | sort -z | xargs -0r sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)
env_hash=$(env | grep -E '^(RUSTFLAGS|RUSTDOCFLAGS|CARGO_)' | sort | sha256sum | cut -d' ' -f1)
toolchain=$(rustc -V 2>/dev/null || echo unknown)
cmd_norm=$(printf '%s' "cargo $*" | tr -s '[:space:]' ' ')
key=$(printf '%s' "$head_oid:$diff_hash:$untracked_hash:$toolchain:$env_hash:$cmd_norm" \
      | sha256sum | cut -c1-32)

# Replay the newest live record for $key, if fresh and unforced. Returns 1 on miss.
replay_if_hit() {
  [[ "${CLAUDIUS_FORCE:-0}" == 1 || ! -f "$RECORDS" ]] && return 1
  local hit ts rc logf rec_epoch now
  hit=$(grep -F "\"key\":\"$key\"" "$RECORDS" 2>/dev/null | tail -1) || return 1
  [[ -n "$hit" ]] || return 1
  ts=$(jq -r '.ts // empty' <<<"$hit" 2>/dev/null)
  rc=$(jq -r '.exit // empty' <<<"$hit" 2>/dev/null)
  logf=$(jq -r '.log // empty' <<<"$hit" 2>/dev/null)
  [[ -n "$ts" && -n "$rc" && -n "$logf" && -f "$logf" ]] || return 1
  # TTL guards against environment drift (system libs, network deps) the key
  # can't see. Non-GNU `date -d` => treat as a miss (re-run) rather than trust it.
  rec_epoch=$(date -d "$ts" +%s 2>/dev/null) || return 1
  now=$(date +%s)
  (( now - rec_epoch < TTL_HOURS * 3600 )) || return 1
  echo "=== CACHED verification: identical command on identical tree, recorded $ts, exit $rc ==="
  echo "=== Full log: $logf | force a real re-run: CLAUDIUS_FORCE=1 $0 $* ==="
  tail -100 "$logf"
  exit "$rc"
}

replay_if_hit "$@"

# Serialize concurrent identical runs: a second agent blocks on the first, then
# replays its freshly written record instead of duplicating the build. flock is
# Linux/util-linux; if absent, skip locking (correctness holds, dedup weakens).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LEDGER_DIR/locks/$key.lock" 2>/dev/null || true
  if ! flock -n 9 2>/dev/null; then
    echo "=== identical command already running under another agent; waiting for its result ==="
    # -w below the session Bash timeout; on timeout we degrade to running (never wedge).
    if flock -w 570 9 2>/dev/null; then replay_if_hit "$@"; fi
  fi
fi

# --- Miss: run for real, capture full log, record the outcome --------------
logf="$LEDGER_DIR/logs/$(date +%Y%m%dT%H%M%S)-$key.log"
start=$EPOCHSECONDS
cargo "$@" 2>&1 | tee "$logf" | tail -100
rc=${PIPESTATUS[0]}
dur=$(( EPOCHSECONDS - start ))
# duration_s is recorded on purpose: a corrupted cargo fingerprint can make a
# suite falsely report "Finished" in ~0.3s (a false green). Recorded duration
# turns that invisible trap into an auditable anomaly.
record=$(jq -cn --arg ts "$(date -Is)" --arg key "$key" --arg cmd "$cmd_norm" \
  --arg head "$head_oid" --arg log "$logf" \
  --argjson exit "$rc" --argjson dur "$dur" --arg sid "${CLAUDE_SESSION_ID:-}" \
  '{ts:$ts,key:$key,cmd:$cmd,head:$head,exit:$exit,duration_s:$dur,log:$log,session:$sid}')
if command -v flock >/dev/null 2>&1; then
  printf '%s\n' "$record" | flock "$RECORDS" tee -a "$RECORDS" >/dev/null
else
  printf '%s\n' "$record" >> "$RECORDS"
fi
echo "=== exit $rc | full log: $logf | recorded in verification ledger (key $key) ==="
exit "$rc"
