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
# sha256sum is GNU coreutils, not universal (e.g. stock macOS ships `shasum`
# instead) — every hash below, INCLUDING the key itself, silently collapses to
# an empty string without it, and an empty key matches every other empty-key
# record in the ledger (cross-command replay poisoning). Fail open instead.
command -v sha256sum >/dev/null 2>&1 || exec cargo "$@"
command -v xargs >/dev/null 2>&1 || exec cargo "$@"
mkdir -p "$LEDGER_DIR/logs" "$LEDGER_DIR/locks" 2>/dev/null || exec cargo "$@"
git rev-parse --show-toplevel >/dev/null 2>&1 || exec cargo "$@"

# --- Cache key: everything that determines the result ----------------------
head_oid=$(git rev-parse HEAD 2>/dev/null) || exec cargo "$@"
diff_hash=$(git diff HEAD 2>/dev/null | sha256sum | cut -d' ' -f1)
# Untracked, non-ignored files: agents routinely create new source before testing.
# `-r`/--no-run-if-empty is a GNU xargs extension BSD/macOS xargs rejects.
# Without it, zero untracked files still runs sha256sum once with an already-
# drained stdin, hashing empty input — deterministic and portable either way.
untracked_hash=$(git ls-files --others --exclude-standard -z 2>/dev/null \
  | sort -z | xargs -0 sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)
env_hash=$(env | grep -E '^(RUSTFLAGS|RUSTDOCFLAGS|CARGO_)' | sort | sha256sum | cut -d' ' -f1)
toolchain=$(rustc -V 2>/dev/null || echo unknown)
# Repo-relative invocation dir: `cargo test` without `-p` scopes to the cwd's
# workspace member, so the same command string means something different from
# a member dir vs the workspace root — that must be part of what makes a tree+
# command combination unique.
rel_dir=$(git rev-parse --show-prefix 2>/dev/null)
cmd_norm=$(printf '%s' "cargo $*" | tr -s '[:space:]' ' ')
key=$(printf '%s' "$head_oid:$diff_hash:$untracked_hash:$toolchain:$env_hash:$rel_dir:$cmd_norm" \
      | sha256sum | cut -c1-32)
# Belt-and-braces: an empty key (e.g. a hashing tool failed silently above)
# must never be looked up or recorded — it would alias every other empty key.
[[ -n "$key" ]] || exec cargo "$@"

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
  # can't see. `date -d` is a GNU extension BSD/macOS date lacks; the log file's
  # own mtime is portable (GNU `stat -c`, BSD `stat -f`) and free either way.
  rec_epoch=$(stat -c %Y "$logf" 2>/dev/null) || rec_epoch=$(stat -f %m "$logf" 2>/dev/null)
  [[ -n "$rec_epoch" ]] || return 1
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
    # -w assumes the CALLER's Bash-tool timeout, not this script's. The Bash
    # tool defaults to 120s (callers may raise it up to 600s); 100s stays under
    # the common default so a timed-out wait still degrades to running instead
    # of the wait itself getting killed mid-flock.
    if flock -w 100 9 2>/dev/null; then replay_if_hit "$@"; fi
  fi
fi

# Opportunistic prune (best-effort, not every run — rewriting records.jsonl is
# O(n); ~1-in-20 misses is enough to keep it bounded without taxing every
# invocation). TTL only ever gated replay; nothing deleted logs/records before.
find "$LEDGER_DIR/logs" -type f -mmin "+$(( TTL_HOURS * 60 ))" -delete 2>/dev/null || true
if [[ -f "$RECORDS" ]] && (( RANDOM % 20 == 0 )); then
  tmp_records="$RECORDS.tmp.$$"
  : > "$tmp_records" 2>/dev/null
  while IFS= read -r line; do
    rec_log=$(jq -r '.log // empty' <<<"$line" 2>/dev/null)
    [[ -n "$rec_log" && -f "$rec_log" ]] && printf '%s\n' "$line" >> "$tmp_records"
  done < "$RECORDS"
  mv "$tmp_records" "$RECORDS" 2>/dev/null || rm -f "$tmp_records" 2>/dev/null
fi

# --- Miss: run for real, capture full log, record the outcome --------------
# PID suffix avoids two concurrent identical runs in the same second colliding
# on one log file (interleaved/corrupted output) when flock is unavailable.
logf="$LEDGER_DIR/logs/$(date +%Y%m%dT%H%M%S)-$key-$$.log"
start=$(date +%s)
cargo "$@" 2>&1 | tee "$logf" | tail -100
rc=${PIPESTATUS[0]}
dur=$(( $(date +%s) - start ))
# duration_s is recorded on purpose: a corrupted cargo fingerprint can make a
# suite falsely report "Finished" in ~0.3s (a false green). Recorded duration
# turns that invisible trap into an auditable anomaly.
# `date -Is` is a GNU extension; BSD/macOS date lacks it and would write an
# empty $ts, permanently un-replayable (replay treats a missing ts as a miss).
# `-u +%Y-%m-%dT%H:%M:%SZ` is identical output on GNU and BSD date, and GNU
# `date -d` (the read side, above) parses it back without trouble.
record=$(jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg key "$key" --arg cmd "$cmd_norm" \
  --arg head "$head_oid" --arg log "$logf" \
  --argjson exit "$rc" --argjson dur "$dur" --arg sid "${CLAUDE_SESSION_ID:-}" \
  '{ts:$ts,key:$key,cmd:$cmd,head:$head,exit:$exit,duration_s:$dur,log:$log,session:$sid}')
if command -v flock >/dev/null 2>&1; then
  printf '%s\n' "$record" | flock "$RECORDS" tee -a "$RECORDS" >/dev/null
else
  printf '%s\n' "$record" >> "$RECORDS"
fi
echo "=== exit $rc | full log: $logf | recorded in verification ledger (key $key) ==="

# --- Fake-green guard: implausibly fast verification ------------------------
# A test/clippy/nextest MISS must compile and run for real, so a ~0s finish means
# cargo built nothing and ran a PRE-EXISTING binary. Cargo records dep-info paths
# relative to the crate root, so two worktrees at the same HEAD collide on one
# artifact path in a shared target dir: the binary that ran can be a CONCURRENT
# agent's build — green without ever containing this agent's tests. A legitimate
# no-op re-run looks identical from here, so this only WARNS: rc is never touched
# and any internal failure degrades to silence (fail-open, per the header).
warn_if_implausibly_fast() {
  local min sub arg
  # 2s: a genuine compile+link+run of a test/clippy target costs seconds even on a
  # warm cache; below that, cargo has done no build work at all. 0 disables.
  min="${CLAUDIUS_MIN_PLAUSIBLE_DUR:-2}"
  [[ "$min" =~ ^[0-9]+$ ]] || min=2
  (( min > 0 )) || return 0
  [[ "${dur:-}" =~ ^[0-9]+$ ]] || return 0
  (( dur < min )) || return 0
  # The subcommand is the first non-flag arg (`+toolchain` and flags precede it).
  for arg in "$@"; do
    case "$arg" in -*|+*) ;; *) sub="$arg"; break ;; esac
  done
  case "${sub:-}" in test|clippy|nextest) ;; *) return 0 ;; esac
  cat <<BANNER
!!! --------------------------------------------------------------------------
!!! WARNING: POSSIBLE FAKE GREEN — this run finished in ${dur}s (below ${min}s),
!!! so cargo may have compiled little (or nothing) and executed a PRE-EXISTING binary. Worktrees at
!!! this same HEAD ($head_oid) can share one target dir and collide on the same
!!! artifact path, so that binary may be ANOTHER agent's build.
!!! 1. Before trusting this result, confirm YOUR new/renamed test names appear
!!!    in the output above (full log: $logf).
!!! 2. If they do not, this is NOT evidence. Re-run genuinely isolated:
!!!      CARGO_TARGET_DIR=<your-own-dir> CLAUDIUS_FORCE=1 $0 $*
!!! Tune or silence this guard with CLAUDIUS_MIN_PLAUSIBLE_DUR (0 = off).
!!! --------------------------------------------------------------------------
BANNER
}
warn_if_implausibly_fast "$@" || true

exit "$rc"
