#!/usr/bin/env bash
# Verification ledger for cargo. Usage: cargo-cached.sh <cargo args...>
#   e.g. cargo-cached.sh clippy -p my-crate --all-targets -- -D warnings
#
# Identical command + identical tree in the same checkout => REPLAY the recorded
# log + exit code (the agent gets its output at zero compile cost). Otherwise run
# the real cargo, save the full log, and append a JSONL record to the ledger.
#
# Cache infrastructure failures (missing jq, not a git repo, no flock) fail open
# to plain cargo. Auto-isolation setup fails closed because a shared target dir
# can make cargo report stale artifacts as fresh under concurrent checkouts.
#
# Ledger location is portable — NEVER hardcoded. A user who wants it elsewhere
# (e.g. a big disk) sets CLAUDIUS_CACHE_DIR; otherwise it follows the XDG cache.
# CLAUDIUS_FORCE=1 skips replay. CLAUDIUS_MAX_PARALLEL_BUILDS (default 2) caps
# cache misses across wrappers sharing the per-user /tmp build lock directory.
# Use the same absolute CLAUDIUS_BUILD_LOCK_DIR in every session to override it.
# If callers request different limits, use the lowest limit among live builds
# and the build seeking admission.
# CLAUDIUS_BUILD_SLOT_WAIT_SECONDS (default 300, 0 for an immediate attempt)
# bounds admission and slot wait. A timeout exits 75 without running Cargo.
set -uo pipefail

# A spawned agent's Bash tool can start with a PATH that omits ~/.cargo/bin
# (rustup's install location) even though the invoking user's interactive
# shell has it — every such agent hits "cargo: command not found" on its
# first wrapped call. Prepend it defensively; a no-op when already present
# or when cargo lives elsewhere (e.g. a system package).
if [[ -n "${HOME:-}" ]]; then
  [[ ":$PATH:" == *":$HOME/.cargo/bin:"* ]] || PATH="$HOME/.cargo/bin:$PATH"
fi

CACHE_ROOT="${CLAUDIUS_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/claudius}"
TTL_HOURS=24

command -v jq >/dev/null 2>&1 || exec cargo "$@"
# sha256sum is GNU coreutils, not universal (e.g. stock macOS ships `shasum`
# instead) — every hash below, INCLUDING the key itself, silently collapses to
# an empty string without it, and an empty key matches every other empty-key
# record in the ledger (cross-command replay poisoning). Fail open instead.
command -v sha256sum >/dev/null 2>&1 || exec cargo "$@"
command -v xargs >/dev/null 2>&1 || exec cargo "$@"
# Capture and canonicalize the checkout root once. It guards git-dependent cache
# operations and identifies both the ledger key and isolated target directory.
toplevel=$(git rev-parse --show-toplevel 2>/dev/null)
[[ -n "$toplevel" ]] || exec cargo "$@"
toplevel=$(cd "$toplevel" 2>/dev/null && pwd -P)
[[ -n "$toplevel" ]] || exec cargo "$@"

prepare_ledger() {
  local probe="$LEDGER_DIR/locks/.write-test.$$"
  mkdir -p "$LEDGER_DIR/logs" "$LEDGER_DIR/locks" 2>/dev/null || return 1
  ( umask 077; : > "$probe" ) 2>/dev/null || return 1
  rm -f "$probe" 2>/dev/null || return 1
}

LEDGER_DIR="$CACHE_ROOT/ledger"
RECORDS="$LEDGER_DIR/records.jsonl"
if ! prepare_ledger; then
  primary_ledger_dir="$LEDGER_DIR"
  LEDGER_DIR="$toplevel/.claudius-ledger"
  RECORDS="$LEDGER_DIR/records.jsonl"
  if ! prepare_ledger; then
    echo "claudius: ledger unavailable at $primary_ledger_dir AND workspace-local $LEDGER_DIR (not writable); running cargo directly, WITHOUT replay/dedup/fake-green protection" >&2
    exec cargo "$@"
  fi
  echo "claudius: ledger unavailable at $primary_ledger_dir (not writable); using workspace-local ledger $LEDGER_DIR" >&2
fi

# Capture an explicit CARGO_TARGET_DIR or --target-dir before auto-derivation;
# replay identity and diagnostics depend on who selected the target directory.
caller_target_dir="${CARGO_TARGET_DIR:-}"
cli_target_dir=""
cli_args=("$@")
for ((arg_index = 0; arg_index < ${#cli_args[@]}; arg_index++)); do
  case "${cli_args[arg_index]}" in
    --) break ;;
    --target-dir)
      if (( arg_index + 1 < ${#cli_args[@]} )); then
        caller_target_dir="${cli_args[arg_index + 1]}"
        cli_target_dir="$caller_target_dir"
      fi
      break
      ;;
    --target-dir=*)
      caller_target_dir="${cli_args[arg_index]#--target-dir=}"
      cli_target_dir="$caller_target_dir"
      break
      ;;
  esac
done
auto_isolated=0

# --- Structural per-checkout target-dir isolation ---------------------------
# Two agents building the SAME commit in separate checkouts (git worktrees OR
# independent clones/copies) that share one CARGO_TARGET_DIR silently collide:
# cargo records dep-info source paths RELATIVE to the crate root, so identical
# HEADs yield the identical artifact path under target/debug/deps/. Cargo then
# mtime-checks checkout A's edits against checkout B's freshly-built binary,
# declares A "fresh", and runs B's binary while reporting it as A's own pass/fail
# (rust-lang/cargo#12516, #7740, #14053, #13259 — a documented, longstanding
# cargo limitation). Defuse it structurally: each checkout builds into its OWN
# target dir, derived deterministically from the checkout's absolute path.
# Path-keyed, NOT worktree-topology-keyed (no --git-common-dir vs --git-dir
# check): independent clones of the same repo at the same commit are each their
# own "primary" tree yet collide identically, and hashing the path covers
# worktrees, clones and submodules uniformly. Deterministic — a checkout's own
# repeat builds reuse the same dir and stay warm. An explicit caller-selected
# CARGO_TARGET_DIR or --target-dir is the manual escape hatch.
# NOTE: these default <canonical>/claudius-checkouts/<hash> dirs (or
# CLAUDIUS_TARGET_PREFIX/<hash>) accumulate PERMANENTLY — there is deliberately
# NO automatic GC. Pruning stale ones is the user's/coordinator's responsibility.
resolve_target_root() {
  local timeout_seconds="$1" canonical
  canonical=$(timeout "$timeout_seconds" cargo metadata --format-version 1 --no-deps 2>/dev/null \
    | jq -r '.target_directory // empty' 2>/dev/null) || return 1
  [[ -n "$canonical" ]] || return 1
  target_root="${canonical%/}/claudius-checkouts"
}

if [[ -z "$caller_target_dir" ]]; then
  if [[ -n "${CLAUDIUS_TARGET_PREFIX:-}" ]]; then
    target_root="${CLAUDIUS_TARGET_PREFIX%/}"
  elif command -v timeout >/dev/null 2>&1; then
    # Resolve cargo's true default before setting our override. Cargo metadata
    # can block on its internal locks, so retry once with a longer timeout.
    if ! resolve_target_root 3 && ! resolve_target_root 15; then
      echo "claudius: ERROR: cannot establish per-checkout isolation: cargo metadata failed after 2 attempts (timeouts: 3s, 15s); refusing to use cargo's shared/default target dir" >&2
      exit 1
    fi
  else
    echo "claudius: ERROR: cannot establish per-checkout isolation: timeout unavailable; refusing to use cargo's shared/default target dir" >&2
    exit 1
  fi

  tl_hash=$(printf '%s' "$toplevel" | sha256sum | cut -c1-16)
  derived="${target_root%/}/$tl_hash"
  if ! mkdir -p "$derived" 2>/dev/null; then
    echo "claudius: ERROR: cannot establish per-checkout isolation: could not create $derived; refusing to use cargo's shared/default target dir" >&2
    exit 1
  fi
  export CARGO_TARGET_DIR="$derived"
  auto_isolated=1
fi
effective_target_dir="${cli_target_dir:-${CARGO_TARGET_DIR:-}}"

# --- Cache key: everything that determines the result ----------------------
head_oid=$(git rev-parse HEAD 2>/dev/null) || exec cargo "$@"
diff_hash=$(git diff HEAD 2>/dev/null | sha256sum | cut -d' ' -f1)
# Untracked, non-ignored files: agents routinely create new source before testing.
# `-r`/--no-run-if-empty is a GNU xargs extension BSD/macOS xargs rejects.
# Without it, zero untracked files still runs sha256sum once with an already-
# drained stdin, hashing empty input — deterministic and portable either way.
# The workspace-local ledger is generated output and must not invalidate its own
# replay key when the invoking repository does not ignore it.
untracked_hash=$(git ls-files --others --exclude-standard --exclude='/.claudius-ledger/' -z 2>/dev/null \
  | sort -z | xargs -0 sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)
# The selected target dir's role in the key depends on who set it:
#  - Auto-derived (caller left it unset): pure path noise. The checkout root is
#    keyed independently, so EXCLUDE the wrapper-derived target dir.
#  - Caller-selected explicitly: a verdict input. The environment spelling is
#    included here; the CLI spelling remains in cmd_norm below. Two different
#    explicit dirs must NOT cross-replay. Every other CARGO_* var always counts.
if [[ -n "$caller_target_dir" ]]; then
  env_hash=$(env | grep -E '^(RUSTFLAGS|RUSTDOCFLAGS|CARGO_)' | sort | sha256sum | cut -d' ' -f1)
else
  env_hash=$(env | grep -E '^(RUSTFLAGS|RUSTDOCFLAGS|CARGO_)' | grep -v '^CARGO_TARGET_DIR=' | sort | sha256sum | cut -d' ' -f1)
fi
toolchain=$(rustc -V 2>/dev/null || echo unknown)
# Repo-relative invocation dir: `cargo test` without `-p` scopes to the cwd's
# workspace member, so the same command string means something different from
# a member dir vs the workspace root — that must be part of what makes a tree+
# command combination unique.
rel_dir=$(git rev-parse --show-prefix 2>/dev/null)
normalize_cargo_command() {
  local out="cargo"
  while (( $# )); do
    out+=" $1"
    shift
  done
  printf '%s' "$out" | tr -s '[:space:]' ' '
}
cmd_norm=$(normalize_cargo_command "$@")
checkout_id=$(printf '%s' "$toplevel" | sha256sum | cut -d' ' -f1)
[[ -n "$checkout_id" ]] || exec cargo "$@"
key=$(printf '%s' "$head_oid:$diff_hash:$untracked_hash:$toolchain:$env_hash:$checkout_id:$rel_dir:$cmd_norm" \
      | sha256sum | cut -c1-32)
# Belt-and-braces: an empty key (e.g. a hashing tool failed silently above)
# must never be looked up or recorded — it would alias every other empty key.
[[ -n "$key" ]] || exec cargo "$@"

# --- Shared helpers --------------------------------------------------------
# Safely-quoted reconstruction of THIS invocation, for copy-paste re-run hints
# in banners: `printf %q` per arg preserves boundaries so an arg with spaces or
# shell metacharacters (e.g. --exact 'my test; echo x') can't corrupt the hint.
rerun_cmd() {
  local out a q
  printf -v out '%q' "$0"
  for a in "$@"; do printf -v q ' %q' "$a"; out+="$q"; done
  printf '%s' "$out"
}
SELF_CMD=$(rerun_cmd "$@")

# Renders a banner's target-dir isolation-status line(s). $1=auto_isolated
# (1/true if the WRAPPER derived & exported the dir), $2=effective target dir.
# Describes the state of the run being reported — for a REPLAY that is the
# ORIGINAL run's RECORDED state (read from the matched ledger record), never the
# replaying process's own live environment.
isolation_status_line() {
  local iso="$1" tgt="$2"
  if [[ "$iso" == 1 || "$iso" == true ]]; then
    printf '!!! This ran in its own auto-isolated target dir (%s) — a same-HEAD\n!!! cross-checkout collision should not occur here.' "$tgt"
  else
    printf '!!! This ran WITHOUT claudius auto-isolation (target dir: %s). If that dir\n!!! is shared with another same-HEAD checkout, the collision hazard is LIVE —\n!!! confirm YOUR own test names appear above.' "${tgt:-cargo default}"
  fi
}

# Cargo subcommand = first non-flag token. A value-taking GLOBAL flag consumes
# the NEXT word as its value, so that word must be skipped too — else `-C . test`
# reads "." and `--config X test` reads "X" as the subcommand (false negative),
# while `-C test build` reads "test" (false positive). Joined forms
# (`--color=always`, `-Zfoo`) are single flag tokens needing no skip. List of
# value-taking globals verified against `cargo -h` in this toolchain.
cargo_subcommand() {
  local skip_next=0 arg
  for arg in "$@"; do
    if (( skip_next )); then skip_next=0; continue; fi
    case "$arg" in
      --config|-C|--color|--explain|--target-dir|-Z) skip_next=1 ;;
      -*|+*) ;;
      *) printf '%s' "$arg"; return 0 ;;
    esac
  done
}

# Plausibility threshold in seconds (0 disables). Base-10 forced so a leading
# zero (CLAUDIUS_MIN_PLAUSIBLE_DUR=08/09 -> arithmetic error that silently
# no-ops the guard; =010 -> misread as octal 8) is parsed as the decimal the
# user meant. The regex rejects non-digits; `10#` reinterprets the digits base-10.
fake_green_min() {
  local min="${CLAUDIUS_MIN_PLAUSIBLE_DUR:-2}"
  [[ "$min" =~ ^[0-9]+$ ]] || min=2
  printf '%s' "$(( 10#$min ))"
}

# Replay the newest live record for $key, if fresh and unforced. Returns 1 on miss.
replay_if_hit() {
  [[ "${CLAUDIUS_FORCE:-0}" == 1 || ! -f "$RECORDS" ]] && return 1
  local hit ts rc logf rec_epoch now fg dur_rec rec_tgt rec_autoiso
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
  echo "=== Full log: $logf | force a real re-run: CLAUDIUS_FORCE=1 $SELF_CMD ==="
  tail -100 "$logf"
  # Re-surface a fake-green suspicion recorded on the ORIGINAL run — otherwise the
  # cache launders it into a clean CACHED line for every later agent/TTL window.
  # rc is never touched (warn-only); a missing field on older records reads false.
  fg=$(jq -r '.fake_green_suspected // false' <<<"$hit" 2>/dev/null)
  dur_rec=$(jq -r '.duration_s // empty' <<<"$hit" 2>/dev/null)
  # The isolation status must reflect the ORIGINAL run (this record), not the
  # replaying process. Old records predating these fields read as not-isolated /
  # unknown dir (jq defaults).
  rec_tgt=$(jq -r '.target_dir // empty' <<<"$hit" 2>/dev/null)
  rec_autoiso=$(jq -r '.auto_isolated // false' <<<"$hit" 2>/dev/null)
  if [[ "$fg" == true ]]; then
    cat <<BANNER
!!! --------------------------------------------------------------------------
!!! WARNING: CACHED FAKE-GREEN SUSPECT — this cached result was flagged as
!!! suspiciously fast (${dur_rec}s) when it originally ran, so cargo may have
!!! compiled little (or nothing) and executed a PRE-EXISTING binary. The cache is replaying
!!! that same run: a clean CACHED line is NOT evidence on its own.
!!! Confirm YOUR new/renamed test names appear in the log above ($logf).
$(isolation_status_line "$rec_autoiso" "$rec_tgt")
!!! If the log doesn't name your tests, force a genuine re-run:
!!!   CLAUDIUS_FORCE=1 $SELF_CMD
!!! --------------------------------------------------------------------------
BANNER
  fi
  exit "$rc"
}

replay_if_hit "$@"

# Serialize concurrent identical runs: a second agent blocks on the first, then
# replays its freshly written record instead of duplicating the build. flock is
# Linux/util-linux; if absent, skip locking (correctness holds, dedup weakens).
# A bare `exec 9>f 2>/dev/null` makes the stderr mute PERMANENT for the rest of
# the run; the brace group scopes it to the open alone while fd 9 stays open. A
# failed open short-circuits the `&&`, skipping locking (fail-open).
if command -v flock >/dev/null 2>&1 && { exec 9>"$LEDGER_DIR/locks/$key.lock"; } 2>/dev/null; then
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

# --- Cross-checkout build cap ----------------------------------------------
max_parallel_builds() {
  local max="${CLAUDIUS_MAX_PARALLEL_BUILDS:-2}"
  [[ "$max" =~ ^[0-9]+$ ]] || max=2
  max=$(( 10#$max ))
  (( max > 0 )) || max=2
  printf '%s' "$max"
}

build_lock_error() {
  printf 'claudius: ERROR: cannot coordinate Cargo builds at %s\n' "$1" >&2
  exit 1
}

build_wait_timeout() {
  local location="$1" seconds="$2" holder
  shift 2
  printf 'claudius: timed out waiting for %s after %ss (CLAUDIUS_BUILD_SLOT_WAIT_SECONDS)\n' \
    "$location" "$seconds" >&2
  for holder; do
    [[ -z "$holder" ]] || printf 'claudius: holder: %s\n' "$holder" >&2
  done
  exit 75
}

build_slot_fd=""
acquire_build_slot() {
  local lock_dir="${CLAUDIUS_BUILD_LOCK_DIR:-/tmp/claudius-build-locks-$EUID}"
  local admission="$lock_dir/admission.lock" wait_seconds="${CLAUDIUS_BUILD_SLOT_WAIT_SECONDS:-300}"
  local max deadline admission_fd context holder holder_limit lock_rc slot free_slot fd
  local active allowed slot_count notified=0
  local holders=()

  [[ "$lock_dir" == /* ]] || build_lock_error "$lock_dir (use an absolute path)"
  (umask 077; mkdir -p -- "$lock_dir") 2>/dev/null || build_lock_error "$lock_dir"
  [[ -d "$lock_dir" && ! -L "$lock_dir" && -O "$lock_dir" \
    && "$(stat -c %a -- "$lock_dir")" == 700 ]] || build_lock_error "$lock_dir"
  [[ ! -L "$admission" && ( ! -e "$admission" || -f "$admission" ) ]] || build_lock_error "$admission"
  { exec {admission_fd}>>"$admission"; } 2>/dev/null || build_lock_error "$admission"

  [[ "$wait_seconds" =~ ^[0-9]{1,9}$ ]] || wait_seconds=300
  wait_seconds=$(( 10#$wait_seconds ))
  deadline=$(( SECONDS + wait_seconds ))
  printf -v context 'pid=%s checkout=%q cargo=%q' "$$" "$toplevel" "$cmd_norm"

  # Only the first admitted waiter scans the slots. Later arrivals cannot take
  # a newly freed slot while that waiter holds admission. flock itself is not FIFO.
  if flock -w "$wait_seconds" -E 75 "$admission_fd"; then
    printf '%s\n' "$context" > "$admission" || build_lock_error "$admission"
  else
    lock_rc=$?
    (( lock_rc == 75 )) || build_lock_error "$admission"
    IFS= read -r holder < "$admission" || holder=""
    build_wait_timeout "build admission" "$wait_seconds" "$holder"
  fi

  max=$(max_parallel_builds)
  while :; do
    active=0; allowed=$max; slot_count=0; free_slot=""; holders=()
    for slot in "$lock_dir"/build-slot-*.lock; do
      [[ -e "$slot" || -L "$slot" ]] || continue
      [[ -f "$slot" && ! -L "$slot" ]] || build_lock_error "$slot"
      (( ++slot_count ))
      { exec {fd}>>"$slot"; } 2>/dev/null || build_lock_error "$slot"
      if flock -n -E 75 "$fd"; then
        if [[ -z "$free_slot" ]]; then
          free_slot=$slot
          build_slot_fd=$fd
          continue
        fi
      else
        lock_rc=$?
        (( lock_rc == 75 )) || build_lock_error "$slot"
        # A holder's limit only matters while its slot is locked.
        if ! read -r holder_limit holder < "$slot" || [[ ! "$holder_limit" =~ ^[1-9][0-9]{0,18}$ ]]; then
          holder_limit=1
          holder="$slot (details unavailable)"
        fi
        (( ++active ))
        (( holder_limit < allowed )) && allowed=$holder_limit
        holders+=("$holder")
      fi
      exec {fd}>&-
    done
    if (( active < allowed )); then
      if [[ -z "$free_slot" ]]; then
        free_slot="$lock_dir/build-slot-$slot_count.lock"
        while [[ -e "$free_slot" ]]; do
          (( ++slot_count ))
          free_slot="$lock_dir/build-slot-$slot_count.lock"
        done
        { exec {build_slot_fd}>>"$free_slot"; } 2>/dev/null || build_lock_error "$free_slot"
        flock -n "$build_slot_fd" || build_lock_error "$free_slot"
      fi
      printf '%s %s\n' "$max" "$context" > "$free_slot" || build_lock_error "$free_slot"
      exec {admission_fd}>&-
      return
    fi
    if [[ -n "$free_slot" ]]; then
      exec {build_slot_fd}>&-
      build_slot_fd=""
    fi
    if (( SECONDS >= deadline )); then
      build_wait_timeout "a build slot" "$wait_seconds" "${holders[@]}"
    fi
    if (( ! notified )); then
      printf '=== build slots busy (%s active, limit %s); waiting up to %ss ===\n' "$active" "$allowed" "$wait_seconds" >&2
      printf 'claudius: holder: %s\n' "${holders[@]}" >&2
      notified=1
    fi
    sleep 0.2
  done
}
# Lock order: per-key, admission, then slot. Replays never enter admission,
# and the fake-green stopwatch only measures Cargo.
if command -v flock >/dev/null 2>&1; then acquire_build_slot; fi

run_cargo() (
  exec 9>&-
  if [[ -n "$build_slot_fd" ]]; then exec {build_slot_fd}>&-; fi
  if [[ -n "$log_fd" ]]; then exec >&"$log_fd" 2>&1 {log_fd}>&-; fi
  exec cargo "$@"
)

# --- Miss: run for real, capture full log, record the outcome --------------
# PID suffix avoids two concurrent identical runs in the same second colliding
# on one log file (interleaved/corrupted output) when flock is unavailable.
logf="$LEDGER_DIR/logs/$(date +%Y%m%dT%H%M%S)-$key-$$.log"
# Descendants can keep stdout open after Cargo exits. Appending to a regular
# file preserves live logs and lets the wrapper finish without waiting for EOF.
log_fd=""
if ! { exec {log_fd}>>"$logf"; } 2>/dev/null; then
  printf 'claudius: ledger log unavailable at %s; running Cargo without recording a verdict\n' "$logf" >&2
fi
start=$(date +%s)
# Bash defers a TERM trap while Cargo runs in the foreground. Group TERM
# reaches Cargo too, while wrapper-only TERM keeps the slot until Cargo exits.
trap 'exit 143' TERM
run_cargo "$@"
rc=$?
trap - TERM
if [[ -n "$build_slot_fd" ]]; then exec {build_slot_fd}>&-; fi
[[ -n "$log_fd" ]] || exit "$rc"
exec {log_fd}>&-
dur=$(( $(date +%s) - start ))
tail -100 "$logf"

# Keep target-dir provenance in the full ledger log, not only its JSON record.
if [[ "$auto_isolated" == 1 ]]; then
  printf 'claudius: used isolated target dir: %s\n' "$effective_target_dir" | tee -a "$logf"
else
  printf 'claudius: WARNING: wrapper auto-isolation not used; caller-selected target dir: %s\n' \
    "${effective_target_dir:-cargo default}" | tee -a "$logf"
fi

# Fake-green suspicion, decided ONCE here (see the guard's rationale below) and
# persisted, so a later cache replay can re-surface it instead of laundering it.
# A test/clippy/nextest MISS that finished implausibly fast compiled nothing and
# ran a PRE-EXISTING binary — possibly a concurrent agent's build sharing the
# target dir. rc is never touched (warn-only); any parse failure degrades to false.
fg_min=$(fake_green_min)
fake_green_suspected=false
if (( fg_min > 0 )) && [[ "${dur:-}" =~ ^[0-9]+$ ]] && (( dur < fg_min )); then
  case "$(cargo_subcommand "$@")" in
    test|clippy|nextest) fake_green_suspected=true ;;
  esac
fi

# duration_s is recorded on purpose: a corrupted cargo fingerprint can make a
# suite falsely report "Finished" in ~0.3s (a false green). Recorded duration
# turns that invisible trap into an auditable anomaly.
# `date -Is` is a GNU extension; BSD/macOS date lacks it and would write an
# empty $ts, permanently un-replayable (replay treats a missing ts as a miss).
# `-u +%Y-%m-%dT%H:%M:%SZ` is identical output on GNU and BSD date, and GNU
# `date -d` (the read side, above) parses it back without trouble.
# target_dir + auto_isolated are recorded so a later replay banner reflects THIS
# run's actual isolation state, not the (possibly different-checkout) replayer's.
if [[ "$auto_isolated" == 1 ]]; then auto_isolated_json=true; else auto_isolated_json=false; fi
ledger_session="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-unknown}}"
record=$(jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg key "$key" --arg cmd "$cmd_norm" \
  --arg head "$head_oid" --arg log "$logf" \
  --argjson exit "$rc" --argjson dur "$dur" --arg sid "$ledger_session" \
  --argjson fg "$fake_green_suspected" \
  --arg tgt "$effective_target_dir" --argjson autoiso "$auto_isolated_json" \
  '{ts:$ts,key:$key,cmd:$cmd,head:$head,exit:$exit,duration_s:$dur,fake_green_suspected:$fg,target_dir:$tgt,auto_isolated:$autoiso,log:$log,session:$sid}')
if command -v flock >/dev/null 2>&1; then
  printf '%s\n' "$record" | flock "$RECORDS" tee -a "$RECORDS" >/dev/null
else
  printf '%s\n' "$record" >> "$RECORDS"
fi
echo "=== exit $rc | full log: $logf | recorded in verification ledger (key $key) ==="

# --- Fake-green guard: implausibly fast verification ------------------------
# The suspicion was decided above; this only renders the banner. Per-checkout
# target-dir isolation (top of script) normally prevents the same-HEAD collision,
# but this stays as a residual backstop when the caller deliberately selects a
# possibly shared target directory. There an implausibly fast run may have
# executed a CONCURRENT agent's build, green without ever containing this agent's
# tests. The isolation-status
# line reflects THIS run's actual state (live auto_isolated), so it stays honest
# even when the collision hazard is genuinely live. A legitimate no-op re-run
# looks identical from here, so this only WARNS; rc is never touched (fail-open).
fake_green_banner() {
  cat <<BANNER
!!! --------------------------------------------------------------------------
!!! WARNING: POSSIBLE FAKE GREEN — this run finished in ${dur}s (below ${fg_min}s),
!!! so cargo may have compiled little (or nothing) and executed a PRE-EXISTING binary.
$(isolation_status_line "$auto_isolated" "$effective_target_dir")
!!! 1. Before trusting this result, confirm YOUR new/renamed test names appear
!!!    in the output above (full log: $logf).
!!! 2. If they do not, this is NOT evidence. Force a genuine re-run:
!!!      CLAUDIUS_FORCE=1 $SELF_CMD
!!! Tune or silence this guard with CLAUDIUS_MIN_PLAUSIBLE_DUR (0 = off).
!!! --------------------------------------------------------------------------
BANNER
}
# tee into the log too: a human/coordinator greps $logf directly, and the cache
# replay re-surfaces the banner from the log tail on every later hit.
if [[ "$fake_green_suspected" == true ]]; then
  fake_green_banner | tee -a "$logf"
fi

exit "$rc"
