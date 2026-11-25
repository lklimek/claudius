#!/usr/bin/env bash
# Unit test: cargo-cached.sh verification ledger — key/replay/miss/force logic.
#
# Uses a STUB `cargo` on PATH that increments a counter file per real invocation,
# so "did the real command run?" is observable. Fully isolated: a throwaway git
# repo + a throwaway CLAUDIUS_CACHE_DIR, no real user state touched.
#
#   K1 first run on a tree      -> stub runs (counter 0->1), record written
#   K2 identical run, same tree -> REPLAY, stub NOT re-run (counter stays 1)
#   K3 tree changed (new file)  -> cache MISS, stub re-runs (counter 1->2)
#   K4 CLAUDIUS_FORCE=1         -> forced real run even on a hit (counter 2->3)
#   K5 sha256sum absent on PATH -> fails OPEN to real cargo, no key-collapse
#   K6 same cmd, different cwd  -> cache MISS (cwd is part of the key)
#   K7 real `test` finishing ~0s -> fake-green WARNING, exit code untouched
#   K8 real `test` past threshold-> no warning (a genuine compile takes time)
#   K9 replay of a flagged run   -> re-surfaces the fake-green warning (rc kept)
#   K10 fast non-verification cmd-> no warning (guard is test|clippy|nextest only)
#   K11 --config X before subcmd -> subcommand still detected (was a false-neg)
#   K12 -C test build            -> no warning (real subcommand is build, not "test")
#   K13 -C . test                -> subcommand still detected ("." is -C's value)
#   K14 threshold 08 (leading 0) -> base-10 parse, guard stays active (was disabled)
#   K15 threshold 0              -> guard disabled (documented off switch)
#   K16 threshold non-numeric    -> falls back to the 2s default, still warns
#   K17 concurrent flock replay  -> 2nd proc blocks, replays (rc kept, no re-run)
#   K18 arg with metacharacters  -> re-run recipe stays quoted (boundaries kept)
#   K19 worktree of same repo    -> different auto-derived CARGO_TARGET_DIR
#   K20 two independent clones    -> different auto-derived CARGO_TARGET_DIR
#   K21 same checkout invoked 2x -> SAME derived dir (deterministic, stays warm)
#   K22 explicit CARGO_TARGET_DIR-> respected, not overridden by auto-derivation
#   K23 identical tree, 2 checkouts -> distinct ledger keys (no cross-replay)
#   K24 fake-green banner (auto-isolated) -> names own dir, no manual recipe
#   K25 two DIFFERENT explicit CARGO_TARGET_DIRs -> must NOT cross-replay (in key)
#   K26 sccache present          -> SCCACHE_BASEDIRS not set (cache shared as configured)
#   K28 underivable target dir (mkdir fails) -> wrapper aborts before cargo
#   K29 cargo metadata resolution fails twice -> wrapper aborts before cargo
#   K30 fake-green run in other checkout -> banner names that checkout's dir
#   K31 explicit (shared) override -> banner says hazard LIVE, not "auto-isolated"
#   K33 timeout absent             -> wrapper aborts without blocking
#   K34 target prefix set          -> unique per checkout and stable on repeat
#   K35 explicit target + prefix   -> explicit CARGO_TARGET_DIR wins unchanged
#   K36 target prefix unset        -> existing canonical-derived path is unchanged
#   K37 --target-dir CLI variants  -> distinct keys, no auto-isolation
#   K38 unwritable ledger root     -> workspace-local fallback with one note
#   K39 both ledger roots unwritable -> loud plain-cargo fallback
#   K40 transient metadata failure -> retry succeeds and cargo runs isolated
#   K41 auto-isolated build log    -> records the isolated target dir
#   K42 explicit target build log  -> warns wrapper isolation was not used
#   K43 Claude Code session env     -> preferred ledger session identity
#   K44 Claude session env fallback -> ledger session identity remains attributable
#   K45 no session env              -> ledger records "unknown", never empty
#   K46 cap 1, 2 concurrent builds  -> intervals never overlap
#   K47 cap 2, 3 concurrent builds  -> at most 2 inside cargo at once
#   K48 limits unset, 5 concurrent  -> cap of 4 and 900s wait apply
#   K49 invalid cap and wait        -> fall back to cap of 4 and 900s wait
#   K50 replay while slots saturated-> returns at once, never queues for a slot
#   K51 flock absent                -> cap skipped, both builds run concurrently
#   K52 invalid build lock paths    -> refuse to run uncapped, explain why
#   K53 detached sccache            -> child retains neither wrapper lock
#   K54 detached nextest child      -> live output and exit status survive, replay works
#   K55 workspace-local ledgers     -> different workspaces share the build cap
#   K56 build slot contention       -> older waiter runs before a later arrival
#   K57 wait timeout                -> exit 75, report holder, never run uncapped
#   K58 mixed limits                -> cap 1 waits for all builds and runs alone
#   K59 cancellation                -> process-group TERM releases the build slot
#   K60 wrapper-only TERM           -> slot stays owned until Cargo exits
#   K61 unavailable log file        -> Cargo still runs and no verdict is recorded
#   K62 cancelled admission         -> flock does not retain the per-key lock
#   K63 delayed waiter              -> expired admission cannot start Cargo
#   K64 late orphan writes          -> recorded log and replay stay stable
#   K65 failed log snapshot          -> preserve Cargo verdict without a record
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="${WRAPPER:-$SCRIPT_DIR/../scripts/cargo-cached.sh}"
BASHBIN="$(command -v bash)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export CLAUDIUS_CACHE_DIR="$WORK/cache"   # ledger lives here, outside the repo
export CLAUDIUS_BUILD_LOCK_DIR="$WORK/build-locks"
unset CLAUDIUS_TARGET_PREFIX
unset CLAUDIUS_MAX_PARALLEL_BUILDS   # K48 asserts the built-in default cap
unset CLAUDIUS_BUILD_SLOT_WAIT_SECONDS
COUNTER="$WORK/counter"; echo 0 > "$COUNTER"; export COUNTER
# Fixed "canonical" target dir the stub reports for `cargo metadata` — the wrapper
# derives each checkout's isolated dir UNDER this (see K19-K24).
export STUB_TARGET_DIR="$WORK/canonical-target"

# Stub cargo. `metadata` is the wrapper's canonical-target-dir probe, not a real
# build: emit a fixed target_directory and do NOT count it, so the counter still
# tracks only real runs (every existing K-case asserts exact counts). Any other
# subcommand is a real run: count it, echo an identifiable line, and echo the
# effective CARGO_TARGET_DIR so the isolation tests can see what got derived.
# STUB_SLEEP fakes a real compile's wall clock, STUB_RC its verdict — both default
# to the fast/green stub the key-logic cases (K1-K6) rely on. STUB_MARKER records
# this run's wall-clock interval for the build-slot cap cases (K46-K51).
STUBDIR="$WORK/bin"; mkdir -p "$STUBDIR"
cat > "$STUBDIR/cargo" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = metadata ]; then
  if [ -n "${METADATA_COUNTER:-}" ]; then
    n=$(cat "$METADATA_COUNTER" 2>/dev/null || echo 0)
    echo "$((n + 1))" > "$METADATA_COUNTER"
  fi
  [ "${STUB_METADATA_SLEEP:-0}" != 0 ] && sleep "${STUB_METADATA_SLEEP}"
  [ "${STUB_NO_METADATA:-0}" = 1 ] && exit 0   # emit nothing => canonical empty
  echo "{\"target_directory\":\"${STUB_TARGET_DIR:-$HOME/target}\"}"
  exit 0
fi
# "<START|END> <label> <epoch-ms>" into the shared marker file. flock keeps
# concurrent writers apart where it exists; K51 deliberately runs without it and
# relies on O_APPEND atomicity for these short lines.
mark() {
  [ -n "${STUB_MARKER:-}" ] || return 0
  local line ms
  # Milliseconds, trimmed by hand: `%3N` is a GNU width modifier that uutils
  # coreutils `date` ignores, and raw nanoseconds (19 digits) exceed the integer
  # precision `sort -n`/awk carry when the reader reconstructs the timeline.
  ms=$(date +%s%N); ms=${ms%??????}
  line=$(printf '%s %s %s' "$1" "${STUB_LABEL:-?}" "$ms")
  if command -v flock >/dev/null 2>&1; then
    printf '%s\n' "$line" | flock "$STUB_MARKER" tee -a "$STUB_MARKER" >/dev/null
  else
    printf '%s\n' "$line" >> "$STUB_MARKER"
  fi
}
n=$(cat "$COUNTER" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$COUNTER"
echo "STUB CARGO INVOCATION $n: $*"
echo "STUB_TGT=${CARGO_TARGET_DIR:-}"           # what the wrapper auto-derived/kept
echo "STUB_SCC_BASEDIRS=${SCCACHE_BASEDIRS:-}"  # what the wrapper set for sccache
if [ -n "${STUB_WRAPPER_PID_FILE:-}" ]; then printf '%s\n' "$PPID" > "$STUB_WRAPPER_PID_FILE"; fi
mark START
if [ -n "${STUB_GATE:-}" ]; then
  for ((i = 0; i < 400; i++)); do
    [ -e "$STUB_GATE" ] && break
    sleep 0.05
  done
fi
case "${STUB_ORPHAN:-}" in
  sccache) sccache spawn ;;
  nextest)
    setsid bash -c '
      echo "$$" > "$1"
      [[ -n "$2" ]] || exec sleep 20
      for ((i = 0; i < 400; i++)); do
        if [[ -f "$2" ]]; then
          echo LATE_ORPHAN_OUTPUT
          echo done > "$2.done"
          exit
        fi
        sleep 0.05
      done
    ' _ "$STUB_ORPHAN_PID" "${STUB_ORPHAN_RELEASE:-}" </dev/null &
    ;;
esac
[ "${STUB_SLEEP:-0}" != 0 ] && sleep "${STUB_SLEEP}"
mark END
exit "${STUB_RC:-0}"
EOF
chmod +x "$STUBDIR/cargo"

# Stub sccache (only prepended to PATH for the sccache-specific case).
SCCDIR="$WORK/sccbin"; mkdir -p "$SCCDIR"
cat > "$SCCDIR/sccache" <<'EOF'
#!/usr/bin/env bash
[ "${1:-}" = --version ] && { echo "sccache ${SCC_VER:-0.14.0}"; exit 0; }
if [ "${1:-}" = spawn ]; then
  setsid bash -c 'echo "$$" > "$1"; exec sleep 20' _ "$STUB_ORPHAN_PID" </dev/null >/dev/null 2>&1 &
fi
exit 0
EOF
chmod +x "$SCCDIR/sccache"

# Throwaway git repo (the tree the wrapper keys on).
REPO="$WORK/repo"; mkdir -p "$REPO"
(
  cd "$REPO"
  git init -q
  git config user.email test@example.com
  git config user.name test
  echo "fn main() {}" > src.rs
  git add -A && git commit -qm init
) || { echo "git setup failed"; exit 1; }

counter() { cat "$COUNTER"; }
# Run the wrapper inside the repo with the stub first on PATH. Sets OUT/RC.
run_wrapper() {  # $1=force(0/1) rest=args
  local force="$1"; shift
  OUT=$(cd "$REPO" && CLAUDIUS_FORCE="$force" env PATH="$STUBDIR:$PATH" \
        "$BASHBIN" "$WRAPPER" "$@" 2>&1); RC=$?
}

echo "=== K1: first run misses and executes the real command ==="
run_wrapper 0 test
if [ "$(counter)" = "1" ] && grep -q "STUB CARGO INVOCATION 1" <<<"$OUT" \
   && [ -f "$CLAUDIUS_CACHE_DIR/ledger/records.jsonl" ]; then
  ok "K1 stub ran once and a ledger record was written"
else
  bad "K1 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K2: identical run on identical tree replays (no re-execution) ==="
run_wrapper 0 test
if [ "$(counter)" = "1" ] && grep -q "CACHED verification" <<<"$OUT"; then
  ok "K2 replayed from ledger, stub not re-invoked (counter still 1)"
else
  bad "K2 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K3: changing the tree busts the cache ==="
echo "extra" > "$REPO/newfile.rs"   # untracked, non-ignored => new key
run_wrapper 0 test
if [ "$(counter)" = "2" ] && grep -q "STUB CARGO INVOCATION 2" <<<"$OUT"; then
  ok "K3 new untracked file => cache miss, stub re-ran (counter 2)"
else
  bad "K3 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K4: CLAUDIUS_FORCE=1 forces a real re-run on a hit ==="
run_wrapper 1 test   # identical tree to K3 (a hit), but forced
if [ "$(counter)" = "3" ] && grep -q "STUB CARGO INVOCATION 3" <<<"$OUT"; then
  ok "K4 forced real re-run despite an available hit (counter 3)"
else
  bad "K4 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K5: sha256sum absent falls open to real cargo (no key-collapse) ==="
MINBIN="$WORK/minbin"; mkdir -p "$MINBIN"
for t in bash jq git sort xargs cut date tr mkdir grep tee rm mv cat; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$MINBIN/$t"
done
ln -sf "$STUBDIR/cargo" "$MINBIN/cargo"   # deliberately no sha256sum in $MINBIN
BEFORE=$(counter)
OUT=$(cd "$REPO" && env -i PATH="$MINBIN" HOME="$WORK" \
      CLAUDIUS_CACHE_DIR="$CLAUDIUS_CACHE_DIR" COUNTER="$COUNTER" CLAUDIUS_FORCE=0 \
      "$MINBIN/bash" "$WRAPPER" test 2>&1); RC=$?
AFTER=$(counter)
if [ "$AFTER" = "$((BEFORE + 1))" ] && grep -q "STUB CARGO INVOCATION" <<<"$OUT"; then
  ok "K5 sha256sum absent: fails open to real cargo instead of corrupting the ledger"
else
  bad "K5 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K6: same command from a different cwd is a cache miss (cwd is part of the key) ==="
# Tree/command are identical to the already-cached root invocation (K1-K4) —
# without cwd in the key material this would replay; it must instead miss.
mkdir -p "$REPO/member"
BEFORE=$(counter)
OUT=$(cd "$REPO/member" && CLAUDIUS_FORCE=0 env PATH="$STUBDIR:$PATH" \
      "$BASHBIN" "$WRAPPER" test 2>&1); RC=$?
AFTER=$(counter)
if [ "$AFTER" = "$((BEFORE + 1))" ] && grep -q "STUB CARGO INVOCATION" <<<"$OUT"; then
  ok "K6 same command from a different cwd is a cache miss (cwd is part of the key)"
else
  bad "K6 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

# --- Fake-green guard (implausibly fast verification) -----------------------
WARN="POSSIBLE FAKE GREEN"
bust() { echo "$1" > "$REPO/$1.rs"; }   # untracked file => brand-new key => miss

echo "=== K7: an implausibly fast REAL test run warns without touching the exit code ==="
bust k7
BEFORE=$(counter)
export STUB_RC=7          # a verdict the guard must pass through untouched
run_wrapper 0 test        # stub returns instantly => dur 0s < default threshold
unset STUB_RC
if [ "$(counter)" = "$((BEFORE + 1))" ] && [ "$RC" = "7" ] \
   && grep -q "$WARN" <<<"$OUT" && grep -q "CLAUDIUS_FORCE=1" <<<"$OUT"; then
  ok "K7 fake-green warning raised, exit code still 7 (warn-only, fail-open)"
else
  bad "K7 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K8: a run past the plausibility threshold does not warn ==="
bust k8
BEFORE=$(counter)
export CLAUDIUS_MIN_PLAUSIBLE_DUR=1 STUB_SLEEP=2   # a 2s "compile" clears a 1s bar
run_wrapper 0 test
unset CLAUDIUS_MIN_PLAUSIBLE_DUR STUB_SLEEP
if [ "$(counter)" = "$((BEFORE + 1))" ] && [ "$RC" = "0" ] && ! grep -q "$WARN" <<<"$OUT"; then
  ok "K8 real run slower than the threshold: no warning"
else
  bad "K8 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K9: replaying a flagged run re-surfaces the warning (rc preserved, no re-run) ==="
# The original miss is flagged, so the banner is teed into the log AND the record
# carries fake_green_suspected — the replay must re-surface it, not launder the
# suspicion into a clean CACHED line. RED against the old code (which stripped it).
bust k9
export STUB_RC=4          # a verdict the replay must reproduce untouched
run_wrapper 0 test        # miss: fast REAL run -> flagged, banner logged + recorded
unset STUB_RC
BEFORE=$(counter)
run_wrapper 0 test        # hit: replays the flagged record
if [ "$(counter)" = "$BEFORE" ] && [ "$RC" = "4" ] \
   && grep -q "CACHED verification" <<<"$OUT" && grep -q "$WARN" <<<"$OUT"; then
  ok "K9 replay re-surfaced the fake-green warning, exit 4 preserved, stub not re-run"
else
  bad "K9 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K10: the guard is scoped to verification subcommands only ==="
bust k10
BEFORE=$(counter)
run_wrapper 0 build       # equally fast, but `build` produces no verdict to fake
if [ "$(counter)" = "$((BEFORE + 1))" ] && ! grep -q "$WARN" <<<"$OUT"; then
  ok "K10 fast build does not warn (guard covers test|clippy|nextest only)"
else
  bad "K10 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K11: a value-taking global flag before the subcommand no longer hides it ==="
# `--config net.offline=true test`: old scan took the flag's value as the
# subcommand and never warned on this genuinely-instant test (a false negative).
bust k11
BEFORE=$(counter)
run_wrapper 0 --config net.offline=true test
if [ "$(counter)" = "$((BEFORE + 1))" ] && grep -q "$WARN" <<<"$OUT"; then
  ok "K11 '--config X test' fast run warns (flag value no longer mistaken for the subcommand)"
else
  bad "K11 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K12: a global flag whose value is literally 'test' does not fake a subcommand ==="
# `-C test build`: old scan saw '-C's value "test" and warned on a `build` (a
# false positive — build produces no verdict to fake).
bust k12
BEFORE=$(counter)
run_wrapper 0 -C test build
if [ "$(counter)" = "$((BEFORE + 1))" ] && ! grep -q "$WARN" <<<"$OUT"; then
  ok "K12 '-C test build' does not warn (real subcommand is build, not the -C value 'test')"
else
  bad "K12 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K13: '-C <dir> test' (separate-word flag value) still detects the subcommand ==="
bust k13
BEFORE=$(counter)
run_wrapper 0 -C . test
if [ "$(counter)" = "$((BEFORE + 1))" ] && grep -q "$WARN" <<<"$OUT"; then
  ok "K13 '-C . test' fast run warns ('.' consumed as -C's value, not the subcommand)"
else
  bad "K13 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K14: a leading-zero threshold is parsed base-10, not octal-disabled ==="
# CLAUDIUS_MIN_PLAUSIBLE_DUR=08: old code's `(( 08 > 0 ))` errored ("value too
# great for base") and the `|| return 0` silently disabled the whole guard.
bust k14
BEFORE=$(counter)
export CLAUDIUS_MIN_PLAUSIBLE_DUR=08
run_wrapper 0 test
unset CLAUDIUS_MIN_PLAUSIBLE_DUR
if [ "$(counter)" = "$((BEFORE + 1))" ] && grep -q "$WARN" <<<"$OUT"; then
  ok "K14 threshold 08 warns (base-10 parse; no octal error silently disabling the guard)"
else
  bad "K14 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K15: CLAUDIUS_MIN_PLAUSIBLE_DUR=0 is the documented off switch ==="
bust k15
BEFORE=$(counter)
export CLAUDIUS_MIN_PLAUSIBLE_DUR=0
run_wrapper 0 test        # fast REAL test, but the guard is switched off
unset CLAUDIUS_MIN_PLAUSIBLE_DUR
if [ "$(counter)" = "$((BEFORE + 1))" ] && ! grep -q "$WARN" <<<"$OUT"; then
  ok "K15 threshold 0 disables the guard (no warning on an instant test)"
else
  bad "K15 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K16: a non-numeric threshold falls back to the 2s default (still warns) ==="
bust k16
BEFORE=$(counter)
export CLAUDIUS_MIN_PLAUSIBLE_DUR=abc
run_wrapper 0 test
unset CLAUDIUS_MIN_PLAUSIBLE_DUR
if [ "$(counter)" = "$((BEFORE + 1))" ] && grep -q "$WARN" <<<"$OUT"; then
  ok "K16 non-numeric threshold falls back to 2s and still warns on an instant test"
else
  bad "K16 (counter=$(counter) rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K17: concurrent flock contention -> 2nd process blocks then replays ==="
# A genuine two-process race: proc 1 (slow) holds the lock through its whole run
# and writes the record before releasing; proc 2 starts before that record exists,
# so its first replay misses, it blocks on the lock, then replays on acquisition.
# Isolated cache dir so exactly one key/lock is in play. Not the trivial
# same-process sequential replay (K2/K9) — this exercises the flock-wait branch.
K17CACHE="$WORK/cache-k17"
bust k17
BEFORE=$(counter)
( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K17CACHE" STUB_SLEEP=3 STUB_RC=6 CLAUDIUS_FORCE=0 \
    env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test ) >"$WORK/k17.p1" 2>&1 &
p1=$!
sleep 1   # let proc 1 acquire the lock and enter its slow run before proc 2 starts
OUT=$(cd "$REPO" && CLAUDIUS_CACHE_DIR="$K17CACHE" CLAUDIUS_FORCE=0 \
      env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1); RC=$?
wait "$p1"
AFTER=$(counter)
if [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = "6" ] \
   && grep -q "already running" <<<"$OUT" && grep -q "CACHED verification" <<<"$OUT" \
   && ! grep -q "$WARN" <<<"$OUT"; then
  ok "K17 2nd process waited on the lock then replayed (exit 6, stub ran once, no fake-green warning)"
else
  bad "K17 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K18: the suggested re-run recipe keeps arg boundaries (no metacharacter leak) ==="
# `$0 $*` (old) rendered an arg with spaces/`;` raw into the recipe; printf %q now
# escapes it. Scope the check to the recipe line (the stub echoes the raw args too).
bust k18
run_wrapper 0 test --exact 'boom; echo PWNED'   # instant test -> guard fires -> recipe emitted
recipe=$(grep "CLAUDIUS_FORCE=1" <<<"$OUT")
if grep -q "POSSIBLE FAKE GREEN" <<<"$OUT" \
   && grep -qF 'boom\;\ echo\ PWNED' <<<"$recipe" \
   && ! grep -qF 'boom; echo PWNED' <<<"$recipe"; then
  ok "K18 re-run recipe escapes the metacharacter arg (no raw 'boom; echo PWNED' in the recipe)"
else
  bad "K18 (recipe='${recipe//$'\n'/ }')"
fi

# --- Structural per-checkout target-dir isolation (K19-K24) -----------------
# Force a REAL run and echo the CARGO_TARGET_DIR the wrapper auto-derived/exported.
# CLAUDIUS_FORCE=1 skips replay so the stub always runs (and prints STUB_TGT=).
derived_tgt() {  # $1=dir to run in; echoes the effective CARGO_TARGET_DIR
  local d="$1"; shift
  ( cd "$d" && CLAUDIUS_FORCE=1 env PATH="$STUBDIR:$PATH" \
      "$BASHBIN" "$WRAPPER" test "$@" 2>&1 ) | sed -n 's/^STUB_TGT=//p' | tail -1
}

prefixed_tgt() {  # $1=dir to run in; $2=auto-derived target root
  local d="$1" prefix="$2"
  ( cd "$d" && CLAUDIUS_FORCE=1 CLAUDIUS_TARGET_PREFIX="$prefix" \
      env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 \
  ) | sed -n 's/^STUB_TGT=//p' | tail -1
}

echo "=== K19: a git worktree of the same repo gets its own derived target dir ==="
# A worktree shares the object store (identical HEAD) but lives at a different
# path — the exact production same-HEAD collision scenario. Path-keyed isolation
# must hand it a DIFFERENT target dir from the base checkout.
WT19="$WORK/repo-wt19"
( cd "$REPO" && git worktree add -q --detach "$WT19" HEAD ) 2>/dev/null || { echo "worktree add failed"; exit 1; }
tgt_repo=$(derived_tgt "$REPO")
tgt_wt=$(derived_tgt "$WT19")
if [ -n "$tgt_repo" ] && [ -n "$tgt_wt" ] && [ "$tgt_repo" != "$tgt_wt" ] \
   && [[ "$tgt_repo" == "$STUB_TARGET_DIR/claudius-checkouts/"* ]]; then
  ok "K19 worktree derives a distinct target dir under the canonical root (repo=$tgt_repo wt=$tgt_wt)"
else
  bad "K19 (repo='$tgt_repo' wt='$tgt_wt')"
fi

echo "=== K20: two independent clones at the same commit get different derived dirs ==="
# Independent init/clone (not a worktree) is each its own 'primary' tree yet
# collides identically on a shared target dir — Nagatha flagged this case. Path-
# keying covers it because the toplevel paths differ.
IND_A="$WORK/indep-a"; IND_B="$WORK/indep-b"
for d in "$IND_A" "$IND_B"; do
  mkdir -p "$d"
  ( cd "$d" && git init -q && git config user.email test@example.com && git config user.name test \
    && echo "fn main() {}" > src.rs && git add -A && git commit -qm init ) \
    || { echo "independent repo setup failed"; exit 1; }
done
tgt_a=$(derived_tgt "$IND_A"); tgt_b=$(derived_tgt "$IND_B")
if [ -n "$tgt_a" ] && [ -n "$tgt_b" ] && [ "$tgt_a" != "$tgt_b" ]; then
  ok "K20 independent clones derive distinct target dirs (a=$tgt_a b=$tgt_b)"
else
  bad "K20 (a='$tgt_a' b='$tgt_b')"
fi

echo "=== K21: the same checkout invoked twice derives the SAME dir (deterministic) ==="
# Determinism is what keeps a checkout's own repeat builds warm — the derived dir
# is a pure function of the absolute path, so it must not drift run to run.
tgt_1=$(derived_tgt "$REPO"); tgt_2=$(derived_tgt "$REPO")
if [ -n "$tgt_1" ] && [ "$tgt_1" = "$tgt_2" ]; then
  ok "K21 same checkout path -> same derived target dir across runs ($tgt_1)"
else
  bad "K21 (run1='$tgt_1' run2='$tgt_2')"
fi

echo "=== K22: an explicit caller-set CARGO_TARGET_DIR is respected, not overridden ==="
# The manual escape hatch: if the caller sets CARGO_TARGET_DIR the wrapper must
# leave it exactly as-is (auto-derivation only fills the UNSET case).
EXPLICIT="$WORK/explicit-tgt"
OUT=$( cd "$REPO" && CLAUDIUS_FORCE=1 CARGO_TARGET_DIR="$EXPLICIT" \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )
tgt_explicit=$(sed -n 's/^STUB_TGT=//p' <<<"$OUT" | tail -1)
if [ "$tgt_explicit" = "$EXPLICIT" ]; then
  ok "K22 explicit CARGO_TARGET_DIR left untouched (got '$tgt_explicit')"
else
  bad "K22 (expected '$EXPLICIT' got '$tgt_explicit')"
fi

echo "=== K23: a byte-identical tree in two checkouts gets distinct ledger keys ==="
# Two checkouts of one repo share the object store and can have identical HEAD,
# tracked changes, untracked files, cwd, environment, and command. Their absolute
# checkout roots must still distinguish the ledger verdicts.
KREPO="$WORK/krepo"; mkdir -p "$KREPO"
( cd "$KREPO" && git init -q && git config user.email test@example.com && git config user.name test \
  && echo "fn main() {}" > lib.rs && git add -A && git commit -qm init ) \
  || { echo "krepo setup failed"; exit 1; }
KWT="$WORK/krepo-wt"
( cd "$KREPO" && git worktree add -q --detach "$KWT" HEAD ) 2>/dev/null || { echo "krepo worktree failed"; exit 1; }
K23CACHE="$WORK/cache-k23"
BEFORE=$(counter)
OUT=$( cd "$KREPO" && CLAUDIUS_CACHE_DIR="$K23CACHE" CLAUDIUS_FORCE=0 \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )
MID=$(counter)
OUT2=$( cd "$KWT" && CLAUDIUS_CACHE_DIR="$K23CACHE" CLAUDIUS_FORCE=0 \
        env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 ); RC2=$?
AFTER=$(counter)
key_krepo=$(sed -n '1p' "$K23CACHE/ledger/records.jsonl" | jq -r '.key')
key_kwt=$(sed -n '2p' "$K23CACHE/ledger/records.jsonl" | jq -r '.key')
if [ "$MID" = "$((BEFORE + 1))" ] && [ "$AFTER" = "$((MID + 1))" ] \
   && grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "STUB CARGO INVOCATION" <<<"$OUT2" \
   && ! grep -q "CACHED verification" <<<"$OUT2" \
   && [ -n "$key_krepo" ] && [ -n "$key_kwt" ] && [ "$key_krepo" != "$key_kwt" ]; then
  ok "K23 same-commit checkouts produced distinct keys and both ran cargo"
else
  bad "K23 (before=$BEFORE mid=$MID after=$AFTER rc2=$RC2 key1=$key_krepo key2=$key_kwt out2='${OUT2//$'\n'/ }')"
fi

echo "=== K24: an auto-isolated fake-green banner names its own dir, no manual recipe ==="
# Isolation is structural now, so the old 'CARGO_TARGET_DIR=<your-own-dir>' recipe
# is obsolete; when the wrapper DID auto-isolate, the banner says so and names it.
bust k24
run_wrapper 0 test   # instant real test => fake-green banner fires (auto_isolated=1)
if grep -q "$WARN" <<<"$OUT" && grep -q "CLAUDIUS_FORCE=1" <<<"$OUT" \
   && ! grep -q "CARGO_TARGET_DIR=<your-own-dir>" <<<"$OUT" \
   && grep -q "own auto-isolated target dir" <<<"$OUT"; then
  ok "K24 auto-isolated banner names its own dir, drops the manual CARGO_TARGET_DIR recipe"
else
  bad "K24 (out='${OUT//$'\n'/ }')"
fi

echo "=== K25: two DIFFERENT explicit CARGO_TARGET_DIRs must NOT cross-replay ==="
# The escape hatch (explicit override) is a verdict input: a caller pointing at a
# known-clean dir to force a real re-verify must actually build there, not replay
# a verdict recorded against a DIFFERENT explicit dir. So the two runs on an
# identical tree but different explicit dirs must BOTH execute. RED against the
# unconditional-exclude code (which folds both to one key => 2nd replays).
E25CACHE="$WORK/cache-k25"
BEFORE=$(counter)
OUTA=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$E25CACHE" CLAUDIUS_FORCE=0 CARGO_TARGET_DIR="$WORK/expl-a" \
        env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )
MID=$(counter)
OUTB=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$E25CACHE" CLAUDIUS_FORCE=0 CARGO_TARGET_DIR="$WORK/expl-b" \
        env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )
AFTER=$(counter)
if [ "$MID" = "$((BEFORE + 1))" ] && [ "$AFTER" = "$((MID + 1))" ] \
   && ! grep -q "CACHED verification" <<<"$OUTB" \
   && grep -q "STUB_TGT=$WORK/expl-a" <<<"$OUTA" && grep -q "STUB_TGT=$WORK/expl-b" <<<"$OUTB"; then
  ok "K25 different explicit target dirs each built (no cross-replay; override is in the key)"
else
  bad "K25 (before=$BEFORE mid=$MID after=$AFTER outB='${OUTB//$'\n'/ }')"
fi

echo "=== K26: wrapper leaves SCCACHE_BASEDIRS to the caller (sccache stays shared) ==="
# sccache is one machine-wide cache; the wrapper must not inject per-checkout
# SCCACHE_BASEDIRS. A caller-provided value passes through unchanged.
bust k26
OUT=$( cd "$REPO" && env -u SCCACHE_BASEDIRS PATH="$SCCDIR:$STUBDIR:$PATH" SCC_VER=0.14.0 \
       CLAUDIUS_FORCE=1 "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
OUT2=$( cd "$REPO" && env PATH="$SCCDIR:$STUBDIR:$PATH" SCC_VER=0.14.0 SCCACHE_BASEDIRS=/caller \
       CLAUDIUS_FORCE=1 "$BASHBIN" "$WRAPPER" test 2>&1 )
if [ "$RC" = "0" ] && grep -q "STUB_SCC_BASEDIRS=$" <<<"$OUT" \
   && grep -q "STUB_SCC_BASEDIRS=/caller$" <<<"$OUT2"; then
  ok "K26 sccache present: SCCACHE_BASEDIRS not injected, caller value kept"
else
  bad "K26 (rc=$RC out='${OUT//$'\n'/ }' out2='${OUT2//$'\n'/ }')"
fi

echo "=== K28: an underivable target dir aborts before cargo can use a shared dir ==="
# Make the canonical parent a regular FILE so mkdir -p fails with ENOTDIR.
# Isolation is a correctness boundary: cargo must not run without it.
bust k28
BLOCK="$WORK/blocker-file"; : > "$BLOCK"   # a regular file, not a dir
BEFORE=$(counter)
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" STUB_TARGET_DIR="$BLOCK/sub" CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
if [ "$AFTER" = "$BEFORE" ] && [ "$RC" != "0" ] \
   && ! grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "cannot establish per-checkout isolation: could not create" <<<"$OUT"; then
  ok "K28 mkdir failure aborted loudly before cargo ran"
else
  bad "K28 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K29: repeated cargo metadata failure aborts before cargo runs ==="
bust k29
METADATA_COUNTER="$WORK/metadata-counter-k29"; echo 0 > "$METADATA_COUNTER"
BEFORE=$(counter)
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" STUB_NO_METADATA=1 \
       METADATA_COUNTER="$METADATA_COUNTER" CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
if [ "$(cat "$METADATA_COUNTER")" = 2 ] \
   && [ "$AFTER" = "$BEFORE" ] && [ "$RC" != "0" ] \
   && ! grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "cannot establish per-checkout isolation: cargo metadata failed after 2 attempts" <<<"$OUT"; then
  ok "K29 metadata failed twice and the wrapper aborted loudly before cargo ran"
else
  bad "K29 (metadata=$(cat "$METADATA_COUNTER") before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K30: a fake-green run in another checkout names its own target dir ==="
# Checkout identity prevents B from replaying A's verdict. B's real-run warning
# must therefore describe B's own auto-isolated target directory.
hash_krepo=$(printf '%s' "$KREPO" | sha256sum | cut -c1-16)
hash_kwt=$(printf '%s' "$KWT" | sha256sum | cut -c1-16)
K30CACHE="$WORK/cache-k30"
( cd "$KREPO" && CLAUDIUS_CACHE_DIR="$K30CACHE" CLAUDIUS_FORCE=0 \
    env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test >/dev/null 2>&1 )  # miss, fast => flagged
OUT=$( cd "$KWT" && CLAUDIUS_CACHE_DIR="$K30CACHE" CLAUDIUS_FORCE=0 \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )          # distinct miss
banner=$(grep -A12 "POSSIBLE FAKE GREEN" <<<"$OUT")
if ! grep -q "CACHED verification" <<<"$OUT" \
   && grep -q "POSSIBLE FAKE GREEN" <<<"$OUT" \
   && grep -q "$hash_kwt" <<<"$banner" && ! grep -q "$hash_krepo" <<<"$banner"; then
  ok "K30 second checkout ran and its warning names its own target dir ($hash_kwt)"
else
  bad "K30 (banner='${banner//$'\n'/ }')"
fi

echo "=== K31: an explicit (possibly shared) override banner does NOT falsely claim isolation ==="
# With an explicit override the wrapper did NOT auto-isolate, so the collision
# hazard can be live. The banner must say so, not reassure with 'auto-isolated'.
# RED against the code that hard-coded the 'own isolated dir' wording.
bust k31
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CARGO_TARGET_DIR="$WORK/shared-override" CLAUDIUS_FORCE=0 \
       "$BASHBIN" "$WRAPPER" test 2>&1 )
if grep -q "$WARN" <<<"$OUT" \
   && grep -q "WITHOUT claudius auto-isolation" <<<"$OUT" \
   && ! grep -q "own auto-isolated target dir" <<<"$OUT"; then
  ok "K31 explicit-override banner flags the live hazard, does not falsely claim isolation"
else
  bad "K31 (out='${OUT//$'\n'/ }')"
fi

echo "=== K33: without timeout, the wrapper aborts immediately instead of sharing ==="
NO_TIMEOUT_BIN="$WORK/no-timeout-bin"; mkdir -p "$NO_TIMEOUT_BIN"
for t in bash cat cut date env git grep jq mkdir rm sha256sum sleep sort tail tee tr xargs; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$NO_TIMEOUT_BIN/$t"
done
ln -sf "$STUBDIR/cargo" "$NO_TIMEOUT_BIN/cargo"
METADATA_COUNTER="$WORK/metadata-counter"; echo 0 > "$METADATA_COUNTER"
BEFORE=$(counter)
start=$(date +%s)
OUT=$( cd "$REPO" && env -i PATH="$NO_TIMEOUT_BIN" HOME="$WORK" \
       CLAUDIUS_CACHE_DIR="$WORK/cache-k33" COUNTER="$COUNTER" \
       METADATA_COUNTER="$METADATA_COUNTER" STUB_METADATA_SLEEP=4 \
       STUB_TARGET_DIR="$STUB_TARGET_DIR" CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
elapsed=$(( $(date +%s) - start ))
AFTER=$(counter)
if [ "$(cat "$METADATA_COUNTER")" = 0 ] && [ "$elapsed" -lt 3 ] \
   && [ "$AFTER" = "$BEFORE" ] && [ "$RC" != 0 ] \
   && ! grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "cannot establish per-checkout isolation: timeout unavailable" <<<"$OUT"; then
  ok "K33 timeout absent: wrapper aborted loudly without invoking metadata or cargo"
else
  bad "K33 (metadata=$(cat "$METADATA_COUNTER") elapsed=${elapsed}s before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K34: CLAUDIUS_TARGET_PREFIX keeps targets unique and stable under its root ==="
PREFIX="$WORK/prefixed-targets"
prefix_repo_1=$(prefixed_tgt "$REPO" "$PREFIX")
prefix_repo_2=$(prefixed_tgt "$REPO" "$PREFIX")
prefix_wt=$(prefixed_tgt "$WT19" "$PREFIX")
if [[ "$prefix_repo_1" == "$PREFIX/"* ]] \
   && [[ "$prefix_wt" == "$PREFIX/"* ]] \
   && [ "$prefix_repo_1" = "$prefix_repo_2" ] \
   && [ "$prefix_repo_1" != "$prefix_wt" ] \
   && [ -d "$prefix_repo_1" ] && [ -d "$prefix_wt" ]; then
  ok "K34 prefix roots distinct per-checkout dirs and repeat builds stay warm"
else
  bad "K34 (repo1='$prefix_repo_1' repo2='$prefix_repo_2' wt='$prefix_wt')"
fi

echo "=== K35: explicit CARGO_TARGET_DIR takes precedence over CLAUDIUS_TARGET_PREFIX ==="
PREFIX_EXPLICIT="$WORK/prefix-must-not-win"
EXPLICIT35="$WORK/explicit-must-win"
OUT=$( cd "$REPO" && CLAUDIUS_FORCE=1 CLAUDIUS_TARGET_PREFIX="$PREFIX_EXPLICIT" \
       CARGO_TARGET_DIR="$EXPLICIT35" env PATH="$STUBDIR:$PATH" \
       "$BASHBIN" "$WRAPPER" test 2>&1 )
tgt_explicit35=$(sed -n 's/^STUB_TGT=//p' <<<"$OUT" | tail -1)
if [ "$tgt_explicit35" = "$EXPLICIT35" ] && [ ! -e "$PREFIX_EXPLICIT" ]; then
  ok "K35 explicit target dir won; the unused prefix was not created"
else
  bad "K35 (expected='$EXPLICIT35' got='$tgt_explicit35' prefix_exists=$([ -e "$PREFIX_EXPLICIT" ] && echo yes || echo no))"
fi

echo "=== K36: an unset prefix preserves the existing default path exactly ==="
hash_repo=$(printf '%s' "$REPO" | sha256sum | cut -c1-16)
expected_default="$STUB_TARGET_DIR/claudius-checkouts/$hash_repo"
unset CLAUDIUS_TARGET_PREFIX
default_tgt=$(derived_tgt "$REPO")
if [ "$default_tgt" = "$expected_default" ]; then
  ok "K36 unset prefix kept the existing canonical-derived path byte-for-byte"
else
  bad "K36 (expected='$expected_default' got='$default_tgt')"
fi

echo "=== K37: --target-dir CLI variants stay distinct and skip auto-isolation ==="
K37CACHE="$WORK/cache-k37"
BEFORE=$(counter)
OUT_BASE=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K37CACHE" CLAUDIUS_FORCE=0 \
            CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
            "$BASHBIN" "$WRAPPER" test 2>&1 )
MID=$(counter)
OUT_SEPARATE=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K37CACHE" CLAUDIUS_FORCE=0 \
                CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
                "$BASHBIN" "$WRAPPER" --target-dir "$WORK/cli-target-a" test 2>&1 )
OUT_JOINED=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K37CACHE" CLAUDIUS_FORCE=0 \
              CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
              "$BASHBIN" "$WRAPPER" --target-dir="$WORK/cli-target-b" test 2>&1 )
AFTER_VARIANTS=$(counter)
OUT_PASSTHROUGH=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K37CACHE" CLAUDIUS_FORCE=0 \
                   CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
                   "$BASHBIN" "$WRAPPER" test -- --target-dir "$WORK/test-arg" 2>&1 )
AFTER=$(counter)
record_count=$(wc -l < "$K37CACHE/ledger/records.jsonl")
key_base=$(sed -n '1p' "$K37CACHE/ledger/records.jsonl" | jq -r '.key')
key_separate=$(sed -n '2p' "$K37CACHE/ledger/records.jsonl" | jq -r '.key')
key_joined=$(sed -n '3p' "$K37CACHE/ledger/records.jsonl" | jq -r '.key')
auto_separate=$(sed -n '2p' "$K37CACHE/ledger/records.jsonl" | jq -r '.auto_isolated')
auto_joined=$(sed -n '3p' "$K37CACHE/ledger/records.jsonl" | jq -r '.auto_isolated')
target_separate=$(sed -n '2p' "$K37CACHE/ledger/records.jsonl" | jq -r '.target_dir')
target_joined=$(sed -n '3p' "$K37CACHE/ledger/records.jsonl" | jq -r '.target_dir')
if [ "$MID" = "$((BEFORE + 1))" ] && [ "$AFTER_VARIANTS" = "$((MID + 2))" ] \
   && [ "$AFTER" = "$((AFTER_VARIANTS + 1))" ] \
   && [ "$record_count" = 4 ] \
   && [ -n "$key_base" ] && [ -n "$key_separate" ] && [ -n "$key_joined" ] \
   && [ "$key_base" != "$key_separate" ] \
   && [ "$key_base" != "$key_joined" ] \
   && [ "$key_separate" != "$key_joined" ] \
   && [ "$auto_separate" = false ] && [ "$auto_joined" = false ] \
   && [ "$target_separate" = "$WORK/cli-target-a" ] \
   && [ "$target_joined" = "$WORK/cli-target-b" ] \
   && ! grep -q "CACHED verification" <<<"$OUT_SEPARATE" \
   && ! grep -q "CACHED verification" <<<"$OUT_JOINED" \
   && ! grep -q "CACHED verification" <<<"$OUT_PASSTHROUGH" \
   && grep -q '^STUB_TGT=$' <<<"$OUT_SEPARATE" \
   && grep -q '^STUB_TGT=$' <<<"$OUT_JOINED"; then
  ok "K37 explicit CLI target dirs produced distinct keys and auto_isolated=false"
else
  bad "K37 (before=$BEFORE mid=$MID variants=$AFTER_VARIANTS after=$AFTER records=$record_count keys=$key_base,$key_separate,$key_joined auto=$auto_separate,$auto_joined targets=$target_separate,$target_joined)"
fi

echo "=== K38: an unwritable ledger root falls back inside the checkout ==="
PRIMARY38="$WORK/unwritable-primary"
FALLBACK38="$REPO/.claudius-ledger"
mkdir -p "$PRIMARY38"
chmod 500 "$PRIMARY38"
rm -rf "$FALLBACK38"
bust k38
BEFORE=$(counter)
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$PRIMARY38/cache" CLAUDIUS_FORCE=0 \
       CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
MID=$(counter)
OUT_REPLAY=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$PRIMARY38/cache" CLAUDIUS_FORCE=0 \
              CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
              "$BASHBIN" "$WRAPPER" test 2>&1 ); RC_REPLAY=$?
AFTER=$(counter)
chmod 700 "$PRIMARY38"
fallback_notes=$(grep -c "ledger unavailable.*workspace-local ledger" <<<"$OUT")
if [ "$MID" = "$((BEFORE + 1))" ] && [ "$AFTER" = "$MID" ] \
   && [ "$RC" = 0 ] && [ "$RC_REPLAY" = 0 ] \
   && [ "$fallback_notes" = 1 ] \
   && [ -f "$FALLBACK38/records.jsonl" ] \
   && [ ! -e "$PRIMARY38/cache/ledger/records.jsonl" ] \
   && grep -q "CACHED verification" <<<"$OUT_REPLAY"; then
  ok "K38 unwritable primary emitted one note, recorded locally, and replayed"
else
  bad "K38 (before=$BEFORE mid=$MID after=$AFTER rc=$RC replay_rc=$RC_REPLAY notes=$fallback_notes out='${OUT//$'\n'/ }')"
fi

echo "=== K39: two unwritable ledger roots fall open loudly to plain cargo ==="
PRIMARY39="$WORK/unwritable-primary-both"
FALLBACK39="$REPO/.claudius-ledger"
mkdir -p "$PRIMARY39"
chmod 500 "$PRIMARY39"
rm -rf "$FALLBACK39"
bust k39
chmod 555 "$REPO"
BEFORE=$(counter)
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$PRIMARY39/cache" CLAUDIUS_FORCE=0 \
       CLAUDIUS_MIN_PLAUSIBLE_DUR=0 env PATH="$STUBDIR:$PATH" \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
chmod 755 "$REPO"
chmod 700 "$PRIMARY39"
fallback_notes=$(grep -c "ledger unavailable.*AND workspace-local.*WITHOUT replay/dedup/fake-green protection" <<<"$OUT")
if [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = 0 ] \
   && [ "$fallback_notes" = 1 ] \
   && [ ! -e "$PRIMARY39/cache/ledger/records.jsonl" ] \
   && [ ! -e "$FALLBACK39/records.jsonl" ] \
   && grep -q "STUB CARGO INVOCATION" <<<"$OUT"; then
  ok "K39 dual ledger failure emitted one loud note and ran cargo directly"
else
  bad "K39 (before=$BEFORE after=$AFTER rc=$RC notes=$fallback_notes out='${OUT//$'\n'/ }')"
fi

echo "=== K40: transient metadata failure retries and then builds in isolation ==="
K40CACHE="$WORK/cache-k40"
K40TIMEOUTDIR="$WORK/timeout-k40"; mkdir -p "$K40TIMEOUTDIR"
TIMEOUT_BUDGETS="$WORK/timeout-budgets-k40"; : > "$TIMEOUT_BUDGETS"; export TIMEOUT_BUDGETS
cat > "$K40TIMEOUTDIR/timeout" <<'EOF'
#!/usr/bin/env bash
budget="$1"; shift
printf '%s\n' "$budget" >> "$TIMEOUT_BUDGETS"
[ "$budget" = 3 ] && exit 124
exec "$@"
EOF
chmod +x "$K40TIMEOUTDIR/timeout"
METADATA_COUNTER="$WORK/metadata-counter-k40"; echo 0 > "$METADATA_COUNTER"
BEFORE=$(counter)
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K40CACHE" CLAUDIUS_FORCE=1 \
       METADATA_COUNTER="$METADATA_COUNTER" \
       env PATH="$K40TIMEOUTDIR:$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
AFTER=$(counter)
if [ "$(tr '\n' ' ' < "$TIMEOUT_BUDGETS")" = "3 15 " ] \
   && [ "$(cat "$METADATA_COUNTER")" = 1 ] \
   && [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = 0 ] \
   && grep -q "STUB_TGT=$STUB_TARGET_DIR/claudius-checkouts/" <<<"$OUT"; then
  ok "K40 3s timeout retried at 15s and cargo built in the isolated target dir"
else
  bad "K40 (budgets='$(tr '\n' ' ' < "$TIMEOUT_BUDGETS")' metadata=$(cat "$METADATA_COUNTER") before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K41: an auto-isolated build records target provenance in its full log ==="
K41CACHE="$WORK/cache-k41"
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K41CACHE" CLAUDIUS_FORCE=1 \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
record41=$(tail -1 "$K41CACHE/ledger/records.jsonl")
log41=$(jq -r '.log' <<<"$record41")
target41=$(jq -r '.target_dir' <<<"$record41")
if [ "$RC" = 0 ] && [ -f "$log41" ] \
   && grep -qF "claudius: used isolated target dir: $target41" "$log41"; then
  ok "K41 isolated build log records the target dir used"
else
  bad "K41 (rc=$RC log='$log41' target='$target41' out='${OUT//$'\n'/ }')"
fi

echo "=== K42: a caller-selected build target is visibly not wrapper-isolated ==="
K42CACHE="$WORK/cache-k42"
EXPLICIT42="$WORK/explicit-k42"
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K42CACHE" CLAUDIUS_FORCE=1 \
       CARGO_TARGET_DIR="$EXPLICIT42" env PATH="$STUBDIR:$PATH" \
       "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
record42=$(tail -1 "$K42CACHE/ledger/records.jsonl")
log42=$(jq -r '.log' <<<"$record42")
if [ "$RC" = 0 ] && [ -f "$log42" ] \
   && grep -qF "claudius: WARNING: wrapper auto-isolation not used; caller-selected target dir: $EXPLICIT42" "$log42"; then
  ok "K42 explicit target build log distinguishes caller selection from isolation"
else
  bad "K42 (rc=$RC log='$log42' out='${OUT//$'\n'/ }')"
fi

echo "=== K43: Claude Code session identity takes precedence in ledger records ==="
K43CACHE="$WORK/cache-k43"
OUT=$( cd "$REPO" && CLAUDIUS_CACHE_DIR="$K43CACHE" CLAUDIUS_FORCE=1 \
       CLAUDE_CODE_SESSION_ID="code-session" CLAUDE_SESSION_ID="claude-session" \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
session43=$(tail -1 "$K43CACHE/ledger/records.jsonl" | jq -r '.session')
if [ "$RC" = 0 ] && [ "$session43" = "code-session" ]; then
  ok "K43 preferred Claude Code session identity recorded"
else
  bad "K43 (rc=$RC session='$session43' out='${OUT//$'\n'/ }')"
fi

echo "=== K44: documented Claude session identity remains a supported fallback ==="
K44CACHE="$WORK/cache-k44"
OUT=$( cd "$REPO" && env -u CLAUDE_CODE_SESSION_ID PATH="$STUBDIR:$PATH" \
       CLAUDIUS_CACHE_DIR="$K44CACHE" CLAUDIUS_FORCE=1 \
       CLAUDE_SESSION_ID="claude-session" \
       "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
session44=$(tail -1 "$K44CACHE/ledger/records.jsonl" | jq -r '.session')
if [ "$RC" = 0 ] && [ "$session44" = "claude-session" ]; then
  ok "K44 documented Claude session identity recorded"
else
  bad "K44 (rc=$RC session='$session44' out='${OUT//$'\n'/ }')"
fi

echo "=== K45: missing session identity is explicit rather than empty ==="
K45CACHE="$WORK/cache-k45"
OUT=$( cd "$REPO" && env -u CLAUDE_CODE_SESSION_ID -u CLAUDE_SESSION_ID \
       PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K45CACHE" CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" build 2>&1 ); RC=$?
session45=$(tail -1 "$K45CACHE/ledger/records.jsonl" | jq -r '.session')
if [ "$RC" = 0 ] && [ "$session45" = "unknown" ]; then
  ok "K45 missing session identity recorded as unknown"
else
  bad "K45 (rc=$RC session='$session45' out='${OUT//$'\n'/ }')"
fi

# --- Machine-wide build-slot cap (K46-K51) ----------------------------------
# Each probe launches N concurrent REAL runs that share one ledger (= one slot
# namespace) but carry DISTINCT commands, so none can replay or dedup another and
# every one of them reaches the slot gate. Distinct commands rather than distinct
# untracked files: a file created while a sibling run is hashing the tree would
# race the key computation itself, whereas the command tail is per-process.
slot_probe() {  # $1=cache dir $2=runs $3=stub sleep $4..=extra env; echoes marker file
  local cache="$1" count="$2" nap="$3"; shift 3
  local marker="$cache.markers" i
  local pids=()
  : > "$marker"
  for (( i = 0; i < count; i++ )); do
    ( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$cache" \
        CLAUDIUS_FORCE=0 STUB_SLEEP="$nap" STUB_MARKER="$marker" STUB_LABEL="p$i" \
        "$@" "$BASHBIN" "$WRAPPER" test "--probe-$i" ) >"$cache.out-$i" 2>&1 &
    pids+=($!)
  done
  wait "${pids[@]}"
  printf '%s' "$marker"
}

# Peak number of stub runs simultaneously inside cargo. END sorts before START at
# an identical millisecond (the -k1,1 tiebreak), so a clean hand-off from one
# slot holder to the next never reads as an overlap.
peak_concurrency() {  # $1=marker file
  sort -k3,3n -k1,1 "$1" | awk '$1=="START"{if (++c > m) m = c} $1=="END"{c--} END{print m + 0}'
}

echo "=== K46: CLAUDIUS_MAX_PARALLEL_BUILDS=1 keeps two concurrent real builds apart ==="
marker=$(slot_probe "$WORK/cache-k46" 2 3 CLAUDIUS_MAX_PARALLEL_BUILDS=1)
starts=$(grep -c '^START' "$marker"); ends=$(grep -c '^END' "$marker")
peak=$(peak_concurrency "$marker")
# Exactly one notice in total: the waiter says it on its first missed sweep and
# never again, so a human tailing the output sees "waiting", not a retry loop.
notices=$(cat "$WORK/cache-k46.out-"* | grep -c "build slots busy")
if [ "$starts" = 2 ] && [ "$ends" = 2 ] && [ "$peak" = 1 ] && [ "$notices" = 1 ]; then
  ok "K46 cap 1: both builds ran, intervals never overlapped, one wait notice"
else
  bad "K46 (starts=$starts ends=$ends peak=$peak notices=$notices marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K47: cap 2 admits exactly two of three concurrent real builds at a time ==="
marker=$(slot_probe "$WORK/cache-k47" 3 4 CLAUDIUS_MAX_PARALLEL_BUILDS=2)
starts=$(grep -c '^START' "$marker")
peak=$(peak_concurrency "$marker")
if [ "$starts" = 3 ] && [ "$peak" = 2 ]; then
  ok "K47 cap 2: all three builds ran, never more than two at once"
else
  bad "K47 (starts=$starts peak=$peak marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K48: five builds with defaults admit four and wait up to 900s ==="
marker=$(slot_probe "$WORK/cache-k48" 5 4)
starts=$(grep -c '^START' "$marker")
peak=$(peak_concurrency "$marker")
if [ "$starts" = 5 ] && [ "$peak" = 4 ] \
   && grep -q 'build slots busy (4 active, limit 4); waiting up to 900s' "$WORK/cache-k48.out-"*; then
  ok "K48 default cap of 4 and wait of 900s applied"
else
  bad "K48 (starts=$starts peak=$peak marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K49: invalid cap and wait fall back to the defaults ==="
# Non-numeric, zero and negative are all "the user meant nothing usable" — the
# host must stay protected rather than accept 0/-3 as "unlimited" or abort.
k49_detail=""
for v in abc 0 -3; do
  marker=$(slot_probe "$WORK/cache-k49-$v" 5 3 CLAUDIUS_MAX_PARALLEL_BUILDS="$v" \
    CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=invalid)
  starts=$(grep -c '^START' "$marker")
  peak=$(peak_concurrency "$marker")
  if [ "$starts" != 5 ] || [ "$peak" != 4 ] \
    || ! grep -q 'build slots busy (4 active, limit 4); waiting up to 900s' "$WORK/cache-k49-$v.out-"*; then
    k49_detail+=" [$v: starts=$starts peak=$peak]"
  fi
done
if [ -z "$k49_detail" ]; then
  ok "K49 invalid values used the default cap of 4 and wait of 900s"
else
  bad "K49 ($k49_detail)"
fi

echo "=== K50: a cache replay is never gated on a build slot ==="
# Seed a verdict, then hold the only slot with a long real build on a DIFFERENT
# key. The replay must answer immediately instead of queueing behind the build.
K50CACHE="$WORK/cache-k50"
( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K50CACHE" \
    CLAUDIUS_FORCE=0 "$BASHBIN" "$WRAPPER" test --k50-cached ) >/dev/null 2>&1
( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K50CACHE" \
    CLAUDIUS_FORCE=0 CLAUDIUS_MAX_PARALLEL_BUILDS=1 STUB_SLEEP=8 \
    "$BASHBIN" "$WRAPPER" test --k50-blocker ) >/dev/null 2>&1 &
p50=$!
sleep 2   # let the blocker take the only slot before the replay starts
start=$(date +%s)
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K50CACHE" \
       CLAUDIUS_FORCE=0 CLAUDIUS_MAX_PARALLEL_BUILDS=1 \
       "$BASHBIN" "$WRAPPER" test --k50-cached 2>&1 ); RC=$?
elapsed=$(( $(date +%s) - start ))
wait "$p50"
if [ "$RC" = 0 ] && [ "$elapsed" -lt 4 ] && grep -q "CACHED verification" <<<"$OUT"; then
  ok "K50 replay answered in ${elapsed}s while the only slot was held by a live build"
else
  bad "K50 (rc=$RC elapsed=${elapsed}s out='${OUT//$'\n'/ }')"
fi

echo "=== K51: without flock the cap is skipped entirely (fail open) ==="
NOFLOCKBIN="$WORK/no-flock-bin"; mkdir -p "$NOFLOCKBIN"
for t in bash cat cut date env find git grep head jq mkdir mv rm sha256sum sleep sort stat tail tee timeout tr xargs; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$NOFLOCKBIN/$t"
done
ln -sf "$STUBDIR/cargo" "$NOFLOCKBIN/cargo"   # deliberately no flock in $NOFLOCKBIN
K51MARKER="$WORK/markers-k51"; : > "$K51MARKER"
k51_pids=()
for label in a b; do
  ( cd "$REPO" && env -i PATH="$NOFLOCKBIN" HOME="$WORK" \
      CLAUDIUS_CACHE_DIR="$WORK/cache-k51" COUNTER="$COUNTER" \
      STUB_TARGET_DIR="$STUB_TARGET_DIR" CLAUDIUS_MAX_PARALLEL_BUILDS=1 \
      CLAUDIUS_FORCE=0 STUB_SLEEP=3 STUB_MARKER="$K51MARKER" STUB_LABEL="$label" \
      "$BASHBIN" "$WRAPPER" test "--k51-$label" ) >/dev/null 2>&1 &
  k51_pids+=($!)
done
wait "${k51_pids[@]}"
starts=$(grep -c '^START' "$K51MARKER")
peak=$(peak_concurrency "$K51MARKER")
if [ "$starts" = 2 ] && [ "$peak" = 2 ]; then
  ok "K51 flock absent: both real builds ran concurrently (cap skipped, fail open)"
else
  bad "K51 (starts=$starts peak=$peak marker='$(tr '\n' ' ' < "$K51MARKER")')"
fi

echo "=== K52: invalid lock paths stop the build with a diagnostic ==="
mkdir -m 700 "$WORK/k52-locks"
mkdir "$WORK/k52-locks/build-slot-0.lock"
mkdir -m 755 "$WORK/k52-public"
ln -s "$WORK/k52-locks" "$WORK/k52-symlink"
for broken in "$WORK/k52-locks" "$WORK/k52-public" "$WORK/k52-symlink" k52-relative; do
  OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_FORCE=1 CLAUDIUS_BUILD_LOCK_DIR="$broken" \
         timeout -k 1 3 "$BASHBIN" "$WRAPPER" build --k52 2>&1 ); RC=$?
  if [ "$RC" = 1 ] && grep -q 'cannot coordinate Cargo builds' <<<"$OUT" \
     && ! grep -q 'STUB CARGO INVOCATION' <<<"$OUT"; then
    ok "K52 refused lock path ${broken##*/}"
  else
    bad "K52 (path=$broken rc=$RC output='${OUT//$'\n'/ }')"
  fi
done

wait_for_line() {
  local file="$1" pattern="$2" i
  for (( i = 0; i < 100; i++ )); do
    grep -q -- "$pattern" "$file" 2>/dev/null && return 0
    sleep 0.05
  done
  return 1
}

echo "=== K53: a detached sccache server keeps neither wrapper lock ==="
K53CACHE="$WORK/cache-k53"
K53PID="$WORK/k53.pid"
OUT=$( cd "$REPO" && env PATH="$SCCDIR:$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K53CACHE" \
       CLAUDIUS_MAX_PARALLEL_BUILDS=1 CLAUDIUS_FORCE=1 STUB_ORPHAN=sccache STUB_ORPHAN_PID="$K53PID" \
       timeout -k 1 3 "$BASHBIN" "$WRAPPER" build --k53 2>&1 ); RC=$?
if wait_for_line "$K53PID" '^[0-9][0-9]*$'; then
  orphan_pid=$(cat "$K53PID")
  orphan_fds=$(ls -l "/proc/$orphan_pid/fd" 2>/dev/null)
  OUT2=$( cd "$REPO" && env PATH="$SCCDIR:$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K53CACHE" \
          CLAUDIUS_MAX_PARALLEL_BUILDS=1 CLAUDIUS_FORCE=1 \
          timeout -k 1 3 "$BASHBIN" "$WRAPPER" build --k53 2>&1 ); RC2=$?
  if [ "$RC" = 0 ] && [ "$RC2" = 0 ] && kill -0 "$orphan_pid" 2>/dev/null \
     && grep -q "STUB CARGO INVOCATION" <<<"$OUT2" && ! grep -q '\.lock$' <<<"$orphan_fds"; then
    ok "K53 a forced identical build ran while the detached server stayed alive"
  else
    bad "K53 (first=$RC next=$RC2 fds='${orphan_fds//$'\n'/ }' next output='${OUT2//$'\n'/ }')"
  fi
  kill "$orphan_pid" 2>/dev/null || true
else
  bad "K53 no detached child (rc=$RC output='${OUT//$'\n'/ }')"
fi

echo "=== K54: nextest exits and records the verdict while a child holds stdout ==="
for verdict in 0 7; do
  ORPHAN_PID_FILE="$WORK/k54-$verdict.pid"
  OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_MAX_PARALLEL_BUILDS=1 CLAUDIUS_FORCE=0 \
         STUB_ORPHAN=nextest STUB_ORPHAN_PID="$ORPHAN_PID_FILE" STUB_RC="$verdict" \
         timeout -k 1 3 "$BASHBIN" "$WRAPPER" nextest run "--k54-$verdict" 2>&1 ); RC=$?
  if wait_for_line "$ORPHAN_PID_FILE" '^[0-9][0-9]*$'; then
    orphan_pid=$(cat "$ORPHAN_PID_FILE")
    OUT2=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_MAX_PARALLEL_BUILDS=1 CLAUDIUS_FORCE=0 \
            timeout -k 1 3 "$BASHBIN" "$WRAPPER" nextest run "--k54-$verdict" 2>&1 ); RC2=$?
    OUT3=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_MAX_PARALLEL_BUILDS=1 CLAUDIUS_FORCE=1 \
            STUB_RC="$verdict" timeout -k 1 3 "$BASHBIN" "$WRAPPER" nextest run "--k54-$verdict" 2>&1 ); RC3=$?
    if [ "$RC" = "$verdict" ] && [ "$RC2" = "$verdict" ] && [ "$RC3" = "$verdict" ] \
       && kill -0 "$orphan_pid" 2>/dev/null && grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
       && grep -q "CACHED verification" <<<"$OUT2" && grep -q "STUB CARGO INVOCATION" <<<"$OUT3"; then
      ok "K54 nextest exit $verdict recorded, replayed and rebuilt before the orphan exited"
    else
      bad "K54 (expected=$verdict first=$RC replay=$RC2 forced=$RC3 first output='${OUT//$'\n'/ }')"
    fi
    kill "$orphan_pid" 2>/dev/null || true
  else
    bad "K54 expected=$verdict no detached child (rc=$RC output='${OUT//$'\n'/ }')"
  fi
done

# Waitable stub runs with a hard backstop in case an assertion misses a release.
spawn_build() {
  local checkout="$1" marker="$2" label="$3" limit="$4"; shift 4
  ( cd "$checkout" && exec env PATH="$STUBDIR:$PATH" CLAUDIUS_FORCE=1 \
      STUB_MARKER="$marker" STUB_LABEL="$label" CLAUDIUS_MAX_PARALLEL_BUILDS="$limit" \
      "$@" timeout -k 1 15 "$BASHBIN" "$WRAPPER" test "--$label" ) >"$marker.$label.out" 2>&1 &
  slot_pid=$!
}

echo "=== K55: checkout-local ledger fallback shares the build cap ==="
K55REPO="$WORK/k55-other-checkout"
git clone -q "$REPO" "$K55REPO"
K55CACHE="$WORK/k55-unwritable-cache"
: > "$K55CACHE"
marker="$WORK/k55.marker"; : > "$marker"
spawn_build "$REPO" "$marker" k55a 1 CLAUDIUS_CACHE_DIR="$K55CACHE" STUB_SLEEP=2
p55a=$slot_pid
spawn_build "$K55REPO" "$marker" k55b 1 CLAUDIUS_CACHE_DIR="$K55CACHE" STUB_SLEEP=2
p55b=$slot_pid
wait "$p55a" "$p55b"
starts=$(grep -c '^START' "$marker")
peak=$(peak_concurrency "$marker")
if [ "$starts" = 2 ] && [ "$peak" = 1 ] \
   && grep -q "using workspace-local ledger" "$marker.k55a.out" \
   && grep -q "using workspace-local ledger" "$marker.k55b.out"; then
  ok "K55 both real builds used separate fallback ledgers with no overlap"
else
  bad "K55 (starts=$starts peak=$peak marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K56: a late caller does not overtake the waiting build ==="
marker="$WORK/k56.marker"; : > "$marker"
k56_ready=0
spawn_build "$REPO" "$marker" k56-holder 1 STUB_GATE="$WORK/k56-release"
p56h=$slot_pid
wait_for_line "$marker" '^START k56-holder ' || k56_ready=1
spawn_build "$REPO" "$marker" k56-old 1
p56o=$slot_pid
wait_for_line "$marker.k56-old.out" 'build slots busy' || k56_ready=1
: > "$WORK/k56-release"
wait "$p56h"
spawn_build "$REPO" "$marker" k56-new 1
p56n=$slot_pid
wait "$p56o" "$p56n"
order=$(awk '$1 == "START" { print $2 }' "$marker")
if [ "$k56_ready" = 0 ] && [ "$order" = $'k56-holder\nk56-old\nk56-new' ]; then
  ok "K56 the earlier waiter took the next slot"
else
  bad "K56 (ready=$k56_ready start order='${order//$'\n'/ }')"
fi

echo "=== K57: slot and admission waits time out without running Cargo ==="
marker="$WORK/k57.marker"; : > "$marker"
k57_ready=0
spawn_build "$REPO" "$marker" k57-holder 1 STUB_GATE="$WORK/k57-release"
p57h=$slot_pid
wait_for_line "$marker" '^START k57-holder ' || k57_ready=1
spawn_build "$REPO" "$marker" k57-head 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=7
p57f=$slot_pid
wait_for_line "$marker.k57-head.out" 'build slots busy' || k57_ready=1
spawn_build "$REPO" "$marker" k57-tail 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=1
p57t=$slot_pid
wait "$p57t"; RC1=$?
wait "$p57f"; RC2=$?
: > "$WORK/k57-release"
wait "$p57h"
if [ "$k57_ready" = 0 ] && [ "$RC1" = 75 ] && [ "$RC2" = 75 ] \
   && [ "$(grep -c '^START' "$marker")" = 1 ] \
   && grep -q 'timed out .*1s' "$marker.k57-tail.out" \
   && grep -q 'timed out .*7s' "$marker.k57-head.out" \
   && grep -Eq 'pid=[0-9]+.*checkout=.*cargo=.*--k57-holder' "$marker.k57-head.out"; then
  ok "K57 both wait paths returned 75, reported the timeout and never ran Cargo"
else
  bad "K57 (ready=$k57_ready queued=$RC1 head=$RC2 marker='$(tr '\n' ' ' < "$marker")' head output='$(tr '\n' ' ' < "$marker.k57-head.out")')"
fi

echo "=== K58: cap 1 drains higher-limit builds and runs alone ==="
marker="$WORK/k58.marker"; : > "$marker"
k58_ready=0
spawn_build "$REPO" "$marker" k58-first 2 STUB_GATE="$WORK/k58-release-first"
p58f=$slot_pid
wait_for_line "$marker" '^START k58-first ' || k58_ready=1
spawn_build "$REPO" "$marker" k58-second 2 STUB_GATE="$WORK/k58-release-second"
p58s=$slot_pid
wait_for_line "$marker" '^START k58-second ' || k58_ready=1
spawn_build "$REPO" "$marker" k58-serial 1 STUB_GATE="$WORK/k58-release-serial"
p58o=$slot_pid
wait_for_line "$marker.k58-serial.out" 'build slots busy' || k58_ready=1
: > "$WORK/k58-release-first"
wait "$p58f"
sleep 2.2  # the old retry wakes and would take slot zero while slot one is busy
: > "$WORK/k58-release-second"
wait_for_line "$marker" '^START k58-serial ' || k58_ready=1
spawn_build "$REPO" "$marker" k58-later 2
p58l=$slot_pid
sleep 1
: > "$WORK/k58-release-serial"
wait "$p58s" "$p58o" "$p58l"
order=$(awk '{ print $1, $2 }' "$marker")
if [ "$k58_ready" = 0 ] && [ "$order" = $'START k58-first\nSTART k58-second\nEND k58-first\nEND k58-second\nSTART k58-serial\nEND k58-serial\nSTART k58-later\nEND k58-later' ]; then
  ok "K58 no cargo run overlapped a cap-1 build"
else
  bad "K58 (ready=$k58_ready order='${order//$'\n'/ }')"
fi

echo "=== K59: terminating a build process group releases its slot ==="
marker="$WORK/k59.marker"; : > "$marker"
k59_ready=0
spawn_build "$REPO" "$marker" k59-holder 1 STUB_GATE="$WORK/k59-unused"
p59h=$slot_pid
wait_for_line "$marker" '^START k59-holder ' || k59_ready=1
kill -TERM "$p59h"   # timeout forwards the signal to the group and returns 124
wait "$p59h"; RC1=$?
spawn_build "$REPO" "$marker" k59-retry 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=2
wait "$slot_pid"; RC2=$?
if [ "$k59_ready" = 0 ] && [ "$RC1" = 124 ] && [ "$RC2" = 0 ] \
   && ! grep -q '^END k59-holder ' "$marker" && grep -q '^END k59-retry ' "$marker"; then
  ok "K59 a new build acquired the slot after group cancellation"
else
  bad "K59 (ready=$k59_ready terminated=$RC1 next=$RC2 marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K60: signaling only the wrapper keeps the slot until Cargo exits ==="
marker="$WORK/k60.marker"; : > "$marker"
k60_ready=0
spawn_build "$REPO" "$marker" k60-holder 1 STUB_GATE="$WORK/k60-release" STUB_WRAPPER_PID_FILE="$WORK/k60-wrapper"
p60h=$slot_pid
if wait_for_line "$marker" '^START k60-holder '; then
  kill -TERM "$(cat "$WORK/k60-wrapper")" || k60_ready=1
else
  k60_ready=1
fi
spawn_build "$REPO" "$marker" k60-waiter 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=1
wait "$slot_pid"; RC1=$?
: > "$WORK/k60-release"
wait "$p60h"; RC2=$?
spawn_build "$REPO" "$marker" k60-retry 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=1
wait "$slot_pid"; RC3=$?
if [ "$k60_ready" = 0 ] && [ "$RC1" = 75 ] && [ "$RC2" = 143 ] && [ "$RC3" = 0 ] \
   && ! grep -q '^START k60-waiter ' "$marker" && grep -q '^END k60-holder ' "$marker"; then
  ok "K60 Cargo retained its slot through wrapper-only TERM until it exited"
else
  bad "K60 (ready=$k60_ready waiter=$RC1 terminated=$RC2 retry=$RC3 marker='$(tr '\n' ' ' < "$marker")')"
fi

echo "=== K61: failure opening the log does not fabricate a Cargo result ==="
K61BIN="$WORK/k61bin"; mkdir "$K61BIN"
cat > "$K61BIN/date" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == +%Y%m%dT%H%M%S ]]; then
  echo 'missing-directory/log'
else
  exec "$REAL_DATE" "$@"
fi
EOF
chmod +x "$K61BIN/date"
K61CACHE="$WORK/k61cache"
OUT=$( cd "$REPO" && env PATH="$K61BIN:$STUBDIR:$PATH" REAL_DATE="$(command -v date)" \
       CLAUDIUS_CACHE_DIR="$K61CACHE" CLAUDIUS_FORCE=1 STUB_RC=7 \
       timeout -k 1 3 "$BASHBIN" "$WRAPPER" build --k61 2>&1 ); RC=$?
if [ "$RC" = 7 ] && grep -q 'ledger log unavailable' <<<"$OUT" \
   && grep -q 'STUB CARGO INVOCATION' <<<"$OUT" && [ ! -e "$K61CACHE/ledger/records.jsonl" ]; then
  ok "K61 Cargo ran directly and its exit was never recorded"
else
  bad "K61 (rc=$RC output='${OUT//$'\n'/ }')"
fi

K62BIN="$WORK/k62bin"; mkdir "$K62BIN"
cat > "$K62BIN/flock" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == -w ]]; then
  printf '%s %s\n' "$PPID" "$$" > "$ADMISSION_PIDS"
fi
exec "$REAL_FLOCK" "$@"
EOF
chmod +x "$K62BIN/flock"
REAL_FLOCK=$(command -v flock)

echo "=== K62: cancelling an admission waiter releases its per-key lock ==="
marker="$WORK/k62.marker"; : > "$marker"
K62CACHE="$WORK/k62cache"
spawn_build "$REPO" "$marker" k62-holder 1 STUB_GATE="$WORK/k62-release"
p62h=$slot_pid
wait_for_line "$marker" '^START k62-holder '
spawn_build "$REPO" "$marker" k62-head 1
p62q=$slot_pid
wait_for_line "$marker.k62-head.out" 'build slots busy'
spawn_build "$REPO" "$marker" k62-tail 1 CLAUDIUS_CACHE_DIR="$K62CACHE" \
  PATH="$K62BIN:$STUBDIR:$PATH" REAL_FLOCK="$REAL_FLOCK" ADMISSION_PIDS="$WORK/k62-pids" \
  CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=8
p62t=$slot_pid
if wait_for_line "$WORK/k62-pids" '^[0-9][0-9]* [0-9][0-9]*$'; then
  read -r wrapper_pid flock_pid < "$WORK/k62-pids"
  kill -TERM "$wrapper_pid"
  wait "$p62t"; RC=$?
  key_locks=("$K62CACHE"/ledger/locks/*.lock)
  if [ "$RC" = 143 ] && [ -f "${key_locks[0]}" ] && flock -n "${key_locks[0]}" true; then
    ok "K62 a queued cancellation released its per-key lock"
  else
    bad "K62 per-key lock remained held or wrapper did not stop (rc=$RC)"
  fi
  kill -TERM "$flock_pid" 2>/dev/null || true
else
  bad "K62 admission helper not reached"
fi
: > "$WORK/k62-release"
wait "$p62h" "$p62q" "$p62t"

echo "=== K63: only an unexpired or immediate attempt can admit Cargo ==="
marker="$WORK/k63.marker"; : > "$marker"
spawn_build "$REPO" "$marker" k63-holder 1 STUB_GATE="$WORK/k63-release"
p63h=$slot_pid
wait_for_line "$marker" '^START k63-holder '
spawn_build "$REPO" "$marker" k63-immediate-busy 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=0
wait "$slot_pid"; RC1=$?
spawn_build "$REPO" "$marker" k63-delayed 1 PATH="$K62BIN:$STUBDIR:$PATH" REAL_FLOCK="$REAL_FLOCK" \
  ADMISSION_PIDS="$WORK/k63-pids" CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=1
p63t=$slot_pid
if wait_for_line "$marker.k63-delayed.out" 'build slots busy' && read -r wrapper_pid _ < "$WORK/k63-pids"; then
  kill -STOP "$wrapper_pid"
  sleep 1.2
  : > "$WORK/k63-release"
  wait "$p63h"
  kill -CONT "$wrapper_pid"
  wait "$p63t"; RC2=$?
  spawn_build "$REPO" "$marker" k63-immediate-free 1 CLAUDIUS_BUILD_SLOT_WAIT_SECONDS=0
  wait "$slot_pid"; RC3=$?
  if [ "$RC1" = 75 ] && [ "$RC2" = 75 ] && [ "$RC3" = 0 ] \
     && ! grep -q '^START k63-delayed ' "$marker"; then
    ok "K63 only an unexpired or immediate attempt started Cargo"
  else
    bad "K63 (busy=$RC1 delayed=$RC2 free=$RC3 marker='$(tr '\n' ' ' < "$marker")')"
  fi
else
  : > "$WORK/k63-release"
  wait "$p63h" "$p63t"
  bad "K63 the delayed build did not reach the slot wait"
fi

echo "=== K64: late orphan output cannot change a recorded verdict ==="
K64CACHE="$WORK/k64cache"
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K64CACHE" CLAUDIUS_FORCE=0 \
       STUB_ORPHAN=nextest STUB_ORPHAN_PID="$WORK/k64-pid" STUB_ORPHAN_RELEASE="$WORK/k64-release" \
       timeout -k 1 3 "$BASHBIN" "$WRAPPER" nextest run --k64 2>&1 ); RC=$?
log=$(jq -r .log "$K64CACHE/ledger/records.jsonl" 2>/dev/null)
before=$(sha256sum "$log" 2>/dev/null)
mtime=$(stat -c %y "$log" 2>/dev/null)
: > "$WORK/k64-release"
if wait_for_line "$WORK/k64-release.done" '^done$'; then
  OUT2=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K64CACHE" CLAUDIUS_FORCE=0 \
          timeout -k 1 3 "$BASHBIN" "$WRAPPER" nextest run --k64 2>&1 ); RC2=$?
  if [ "$RC" = 0 ] && [ "$RC2" = 0 ] && grep -q "CACHED verification" <<<"$OUT2" \
     && ! grep -q LATE_ORPHAN_OUTPUT <<<"$OUT2" && [ "$before" = "$(sha256sum "$log")" ] \
     && [ "$mtime" = "$(stat -c %y "$log")" ]; then
    ok "K64 late orphan output changed neither the recorded bytes nor the TTL"
  else
    bad "K64 (rc=$RC replay=$RC2 replay output='${OUT2//$'\n'/ }')"
  fi
else
  bad "K64 orphan did not write late output"
  if read -r orphan_pid < "$WORK/k64-pid"; then kill "$orphan_pid" 2>/dev/null || true; fi
fi

echo "=== K65: snapshot failure preserves the exit without a ledger verdict ==="
K65BIN="$WORK/k65bin"; mkdir "$K65BIN"
printf '#!/bin/sh\nexit 1\n' > "$K65BIN/head"
chmod +x "$K65BIN/head"
K65CACHE="$WORK/k65cache"
OUT=$( cd "$REPO" && env PATH="$K65BIN:$STUBDIR:$PATH" CLAUDIUS_CACHE_DIR="$K65CACHE" \
       CLAUDIUS_FORCE=1 STUB_RC=7 timeout -k 1 3 "$BASHBIN" "$WRAPPER" build --k65 2>&1 ); RC=$?
if [ "$RC" = 7 ] && grep -q 'cannot publish Cargo log' <<<"$OUT" \
   && [ ! -e "$K65CACHE/ledger/records.jsonl" ]; then
  ok "K65 failed snapshots left the Cargo exit intact"
else
  bad "K65 (rc=$RC output='${OUT//$'\n'/ }')"
fi

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
