#!/usr/bin/env bash
# Verification ledger for cargo. Usage: cargo-cached.sh <cargo args...>
#   e.g. cargo-cached.sh clippy -p my-crate --all-targets -- -D warnings
#
# Identical command + identical tree in the same checkout => REPLAY the recorded
# log + exit code (the agent gets its output at zero compile cost). Otherwise run
# the real cargo, tee the full log, and append a JSONL record to the ledger.
#
# FAIL-OPEN throughout: any internal error (missing jq, not a git repo, no flock)
# falls through to a plain `cargo "$@"`. Correctness of a real build always wins
# over the caching optimization.
#
# Ledger location is portable — NEVER hardcoded. A user who wants it elsewhere
# (e.g. a big disk) sets CLAUDIUS_CACHE_DIR; otherwise it follows the XDG cache.
set -uo pipefail

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
  prepare_ledger || exec cargo "$@"
  echo "claudius: ledger unavailable at $primary_ledger_dir (not writable); using workspace-local ledger $LEDGER_DIR" >&2
fi

# Whether the CALLER explicitly set CARGO_TARGET_DIR (vs the wrapper auto-deriving
# it). Captured BEFORE auto-derivation consumes/overwrites it — the env_hash
# branch below depends on this distinction. auto_isolated flips to 1 ONLY when the
# wrapper itself derived and exported the dir (used by the banners + ledger record
# so they never misreport an explicit or absent override as "auto-isolated").
caller_target_dir="${CARGO_TARGET_DIR:-}"
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
# repeat builds reuse the same dir and stay warm. An explicit caller-set
# CARGO_TARGET_DIR is the manual escape hatch and is left untouched.
# NOTE: these default <canonical>/claudius-checkouts/<hash> dirs (or
# CLAUDIUS_TARGET_PREFIX/<hash>) accumulate PERMANENTLY — there is deliberately
# NO automatic GC. Pruning stale ones is the user's/coordinator's responsibility.
if [[ -z "$caller_target_dir" ]]; then
  derivation_ready=0
  derivation_failure="cargo metadata resolution failed"
  if [[ -n "${CLAUDIUS_TARGET_PREFIX:-}" ]]; then
    target_root="${CLAUDIUS_TARGET_PREFIX%/}"
    derivation_ready=1
  elif command -v timeout >/dev/null 2>&1; then
    # Resolve cargo's true default before setting our override. The probe is
    # bounded when timeout exists; without it, skip the potentially locked call.
    canonical=$(timeout 3 cargo metadata --format-version 1 --no-deps 2>/dev/null \
      | jq -r '.target_directory // empty' 2>/dev/null)
    if [[ -n "$canonical" ]]; then
      target_root="${canonical%/}/claudius-checkouts"
      derivation_ready=1
    fi
  else
    derivation_failure="timeout unavailable"
  fi

  if [[ "$derivation_ready" == 1 ]]; then
    tl_hash=$(printf '%s' "$toplevel" | sha256sum | cut -c1-16)
    derived="${target_root%/}/$tl_hash"
    # Export ONLY after the dir exists. A failed mkdir must NOT leave
    # CARGO_TARGET_DIR pointing at an uncreatable path — cargo would then hard-
    # fail (exit 101), that false RED would be ledgered as a real verdict, and
    # (since the auto-derived dir is excluded from the key) replay to every other
    # checkout sharing the tree. On failure, abandon isolation and fall through.
    if mkdir -p "$derived" 2>/dev/null; then
      export CARGO_TARGET_DIR="$derived"
      auto_isolated=1
    else
      echo "claudius: per-checkout isolation skipped (could not create $derived) — using shared/default target dir, same-HEAD collision hazard applies" >&2
    fi
  else
    # Fail open loudly because this drops a correctness protection, not merely
    # an optimization, under the same concurrency that makes collisions likely.
    echo "claudius: per-checkout isolation skipped ($derivation_failure) — using shared/default target dir, same-HEAD collision hazard applies" >&2
  fi
fi

# Keep per-checkout isolation cheap: sccache does NOT cache linker-invoking crates
# (bin/dylib/cdylib/proc-macro — a test binary is a bin, exactly what a test loop
# re-links) and keys on the absolute source path by default, so isolated target
# dirs would each pay a COLD rlib rebuild instead of a relink. SCCACHE_BASEDIRS
# strips the checkout root ($toplevel) from cached paths so the remainder
# (src/lib.rs, ...) is IDENTICAL across checkouts and the rlib cache is shared.
# $HOME would be wrong here — it's a common ancestor of all checkouts, so the
# distinguishing subpath (git/a/... vs git/b/...) still differs after stripping.
# SCCACHE_BASEDIRS landed in sccache 0.14.0 (mozilla/sccache#35); on older builds
# it's silently ignored, so version-gate to avoid claiming an effect we don't get.
version_at_least() {
  local got_major got_minor got_patch min_major min_minor min_patch
  IFS=. read -r got_major got_minor got_patch <<<"$1"
  IFS=. read -r min_major min_minor min_patch <<<"$2"
  got_major=$(( 10#$got_major )); got_minor=$(( 10#$got_minor )); got_patch=$(( 10#$got_patch ))
  min_major=$(( 10#$min_major )); min_minor=$(( 10#$min_minor )); min_patch=$(( 10#$min_patch ))
  (( got_major > min_major \
     || (got_major == min_major && got_minor > min_minor) \
     || (got_major == min_major && got_minor == min_minor && got_patch >= min_patch) ))
}

if command -v sccache >/dev/null 2>&1 && [[ -z "${SCCACHE_BASEDIRS:-}" ]]; then
  scv=$(sccache --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  if [[ -n "$scv" ]] && version_at_least "$scv" 0.14.0; then
    export SCCACHE_BASEDIRS="$toplevel"
  fi
fi

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
# CARGO_TARGET_DIR's role in the key depends on WHO set it:
#  - Auto-derived (caller left it unset): pure path noise. The checkout root is
#    keyed independently, so EXCLUDE the wrapper-derived target dir.
#  - Caller-set explicitly (the CLAUDIUS_ISOLATE_TARGET=1 escape hatch): a verdict
#    input. The caller chose a specific dir precisely to force a real build there
#    (e.g. a known-clean dir for re-verification); two different explicit dirs
#    must NOT cross-replay, so INCLUDE it. Every other CARGO_* var always counts.
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
    case "$1" in
      --)
        while (( $# )); do out+=" $1"; shift; done
        break
        ;;
      --target-dir)
        if (( $# > 1 )); then shift 2; continue; fi
        ;;
      --target-dir=*) shift; continue ;;
    esac
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

# --- Miss: run for real, capture full log, record the outcome --------------
# PID suffix avoids two concurrent identical runs in the same second colliding
# on one log file (interleaved/corrupted output) when flock is unavailable.
logf="$LEDGER_DIR/logs/$(date +%Y%m%dT%H%M%S)-$key-$$.log"
start=$(date +%s)
cargo "$@" 2>&1 | tee "$logf" | tail -100
rc=${PIPESTATUS[0]}
dur=$(( $(date +%s) - start ))

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
record=$(jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg key "$key" --arg cmd "$cmd_norm" \
  --arg head "$head_oid" --arg log "$logf" \
  --argjson exit "$rc" --argjson dur "$dur" --arg sid "${CLAUDE_SESSION_ID:-}" \
  --argjson fg "$fake_green_suspected" \
  --arg tgt "${CARGO_TARGET_DIR:-}" --argjson autoiso "$auto_isolated_json" \
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
# but this stays as a residual backstop for the paths where isolation did NOT
# apply (metadata resolution failed, or an explicit/shared CARGO_TARGET_DIR
# override) — there an implausibly fast run may have executed a CONCURRENT agent's
# build, green without ever containing this agent's tests. The isolation-status
# line reflects THIS run's actual state (live auto_isolated), so it stays honest
# even when the collision hazard is genuinely live. A legitimate no-op re-run
# looks identical from here, so this only WARNS; rc is never touched (fail-open).
fake_green_banner() {
  cat <<BANNER
!!! --------------------------------------------------------------------------
!!! WARNING: POSSIBLE FAKE GREEN — this run finished in ${dur}s (below ${fg_min}s),
!!! so cargo may have compiled little (or nothing) and executed a PRE-EXISTING binary.
$(isolation_status_line "$auto_isolated" "${CARGO_TARGET_DIR:-}")
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
