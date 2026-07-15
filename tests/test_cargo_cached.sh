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
#   K23 identical tree, 2 checkouts -> ledger REPLAY across different target dirs
#   K24 fake-green banner (auto-isolated) -> names own dir, no manual recipe
#   K25 two DIFFERENT explicit CARGO_TARGET_DIRs -> must NOT cross-replay (in key)
#   K26 sccache present + HOME unset -> no crash (SCCACHE_BASEDIRS=toplevel)
#   K27 sccache < 0.14.0 -> SCCACHE_BASEDIRS NOT set (version gate)
#   K28 underivable target dir (mkdir fails) -> isolation abandoned, cargo runs
#   K29 cargo metadata resolution fails -> loud stderr warning, cargo still runs
#   K30 fake-green REPLAY from other checkout -> banner names RECORD's dir
#   K31 explicit (shared) override -> banner says hazard LIVE, not "auto-isolated"
#   K32 BSD sort rejects -V        -> sccache >= 0.14.0 gate still evaluates true
#   K33 timeout absent             -> metadata probe is skipped without blocking
#   K34 target prefix set          -> unique per checkout and stable on repeat
#   K35 explicit target + prefix   -> explicit CARGO_TARGET_DIR wins unchanged
#   K36 target prefix unset        -> existing canonical-derived path is unchanged
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
unset CLAUDIUS_TARGET_PREFIX
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
# to the fast/green stub the key-logic cases (K1-K6) rely on.
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
n=$(cat "$COUNTER" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$COUNTER"
echo "STUB CARGO INVOCATION $n: $*"
echo "STUB_TGT=${CARGO_TARGET_DIR:-}"           # what the wrapper auto-derived/kept
echo "STUB_SCC_BASEDIRS=${SCCACHE_BASEDIRS:-}"  # what the wrapper set for sccache
[ "${STUB_SLEEP:-0}" != 0 ] && sleep "${STUB_SLEEP}"
exit "${STUB_RC:-0}"
EOF
chmod +x "$STUBDIR/cargo"

# Stub sccache (only prepended to PATH for the sccache-specific cases). Reports
# SCC_VER (default 0.14.0, the version SCCACHE_BASEDIRS support landed in) so the
# wrapper's version gate can be exercised both above and below the threshold.
SCCDIR="$WORK/sccbin"; mkdir -p "$SCCDIR"
cat > "$SCCDIR/sccache" <<'EOF'
#!/usr/bin/env bash
[ "${1:-}" = --version ] && { echo "sccache ${SCC_VER:-0.14.0}"; exit 0; }
exit 0
EOF
chmod +x "$SCCDIR/sccache"

# BSD/macOS sort has no -V. This shim preserves ordinary sort behavior but
# rejects -V exactly as a BSD implementation would.
REAL_SORT=$(command -v sort); export REAL_SORT
BSDSORTDIR="$WORK/bsd-sort-bin"; mkdir -p "$BSDSORTDIR"
cat > "$BSDSORTDIR/sort" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = -V ]; then
  echo "sort: illegal option -- V" >&2
  exit 2
fi
exec "$REAL_SORT" "$@"
EOF
chmod +x "$BSDSORTDIR/sort"

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

echo "=== K23: a byte-identical tree in two checkouts REPLAYS across different target dirs ==="
# The core regression: two checkouts of one repo (shared object store => identical
# head_oid/diff_hash/untracked_hash/rel_dir/cmd) differ ONLY in path, hence in the
# auto-derived CARGO_TARGET_DIR. The key must EXCLUDE CARGO_TARGET_DIR so the 2nd
# checkout replays the 1st's record. RED against the old env_hash (which folded
# CARGO_TARGET_DIR in => distinct keys => a miss instead of a replay).
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
tgt_krepo=$(sed -n 's/^STUB_TGT=//p' <<<"$OUT" | tail -1)
MID=$(counter)
OUT2=$( cd "$KWT" && CLAUDIUS_CACHE_DIR="$K23CACHE" CLAUDIUS_FORCE=0 \
        env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 ); RC2=$?
AFTER=$(counter)
if [ "$MID" = "$((BEFORE + 1))" ] && [ "$AFTER" = "$MID" ] \
   && grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "CACHED verification" <<<"$OUT2"; then
  ok "K23 2nd checkout ($KWT, target $tgt_krepo <- 1st's) replayed the 1st's record (no re-run)"
else
  bad "K23 (before=$BEFORE mid=$MID after=$AFTER rc2=$RC2 out2='${OUT2//$'\n'/ }')"
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

echo "=== K26: sccache present with HOME unset does not crash the wrapper ==="
# Old code exported SCCACHE_BASEDIRS=\"\$HOME\" under set -u; an unset HOME aborted
# the whole wrapper instead of falling through. $toplevel (always non-empty) fixes
# it. Stub sccache reports 0.14.0 so the export path actually executes.
bust k26
BEFORE=$(counter)
OUT=$( cd "$REPO" && env -u HOME PATH="$SCCDIR:$STUBDIR:$PATH" SCC_VER=0.14.0 \
       CLAUDIUS_CACHE_DIR="$CLAUDIUS_CACHE_DIR" COUNTER="$COUNTER" \
       STUB_TARGET_DIR="$STUB_TARGET_DIR" CLAUDIUS_FORCE=0 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
tl_expected=$(cd "$REPO" && git rev-parse --show-toplevel)
if [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = "0" ] \
   && grep -q "STUB CARGO INVOCATION" <<<"$OUT" \
   && grep -q "STUB_SCC_BASEDIRS=$tl_expected" <<<"$OUT"; then
  ok "K26 HOME unset + sccache present: wrapper ran (SCCACHE_BASEDIRS=toplevel, no crash)"
else
  bad "K26 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K27: SCCACHE_BASEDIRS is version-gated (skipped below sccache 0.14.0) ==="
# The installed host sccache (0.7.7) predates SCCACHE_BASEDIRS (mozilla/sccache#35,
# 0.14.0). Setting it there is a silent no-op, so the wrapper must NOT set it.
bust k27
OUT=$( cd "$REPO" && env PATH="$SCCDIR:$STUBDIR:$PATH" SCC_VER=0.7.7 CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 )
if grep -q "STUB_SCC_BASEDIRS=$" <<<"$OUT"; then
  ok "K27 sccache 0.7.7: SCCACHE_BASEDIRS left unset (version gate holds)"
else
  bad "K27 (out='${OUT//$'\n'/ }')"
fi

echo "=== K28: an underivable target dir abandons isolation instead of exporting a broken path ==="
# If mkdir on the derived dir fails, the wrapper must NOT leave CARGO_TARGET_DIR
# pointing at an uncreatable path (real cargo would exit 101 and that false RED
# would be ledgered + replayed). It must unset it so cargo falls back. Make the
# canonical parent a regular FILE so mkdir -p fails with ENOTDIR. RED against the
# 'export then mkdir||true' code (which leaves STUB_TGT set to the broken path).
bust k28
BLOCK="$WORK/blocker-file"; : > "$BLOCK"   # a regular file, not a dir
BEFORE=$(counter)
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" STUB_TARGET_DIR="$BLOCK/sub" CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
if [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = "0" ] \
   && grep -q "STUB_TGT=$" <<<"$OUT" \
   && grep -q "isolation skipped (could not create" <<<"$OUT"; then
  ok "K28 mkdir-fail abandons isolation (CARGO_TARGET_DIR unset), wrapper still runs cargo"
else
  bad "K28 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K29: a failed cargo metadata resolution warns loudly and still runs cargo ==="
# Losing isolation drops a CORRECTNESS protection (not just an optimization), so
# unlike the silent fail-open guards this one must be observable on stderr.
bust k29
BEFORE=$(counter)
OUT=$( cd "$REPO" && env PATH="$STUBDIR:$PATH" STUB_NO_METADATA=1 CLAUDIUS_FORCE=1 \
       "$BASHBIN" "$WRAPPER" test 2>&1 ); RC=$?
AFTER=$(counter)
if [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = "0" ] \
   && grep -q "isolation skipped (cargo metadata resolution failed)" <<<"$OUT" \
   && grep -q "STUB_TGT=$" <<<"$OUT"; then
  ok "K29 metadata-fail: loud warning emitted, isolation skipped, cargo still ran"
else
  bad "K29 (before=$BEFORE after=$AFTER rc=$RC out='${OUT//$'\n'/ }')"
fi

echo "=== K30: a cross-checkout fake-green REPLAY banner names the RECORD's dir, not the replayer's ==="
# The whole point of cross-checkout sharing: checkout B replays A's flagged record.
# The replay banner must name A's ORIGINAL dir (from the record), not B's own live
# derived dir. RED against the code that interpolated the live process env.
hash_krepo=$(printf '%s' "$KREPO" | sha256sum | cut -c1-16)
hash_kwt=$(printf '%s' "$KWT" | sha256sum | cut -c1-16)
K30CACHE="$WORK/cache-k30"
( cd "$KREPO" && CLAUDIUS_CACHE_DIR="$K30CACHE" CLAUDIUS_FORCE=0 \
    env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test >/dev/null 2>&1 )  # miss, fast => flagged
OUT=$( cd "$KWT" && CLAUDIUS_CACHE_DIR="$K30CACHE" CLAUDIUS_FORCE=0 \
       env PATH="$STUBDIR:$PATH" "$BASHBIN" "$WRAPPER" test 2>&1 )          # replay B
banner=$(grep -A12 "CACHED FAKE-GREEN SUSPECT" <<<"$OUT")
if grep -q "CACHED FAKE-GREEN SUSPECT" <<<"$OUT" \
   && grep -q "$hash_krepo" <<<"$banner" && ! grep -q "$hash_kwt" <<<"$banner"; then
  ok "K30 replay banner names the record's dir ($hash_krepo), not the replaying checkout's ($hash_kwt)"
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

echo "=== K32: the sccache version gate works when sort rejects GNU-only -V ==="
bust k32
OUT=$( cd "$REPO" && env -u SCCACHE_BASEDIRS PATH="$BSDSORTDIR:$SCCDIR:$STUBDIR:$PATH" \
       SCC_VER=0.14.0 CLAUDIUS_FORCE=1 "$BASHBIN" "$WRAPPER" test 2>&1 )
if grep -q "STUB_SCC_BASEDIRS=$REPO" <<<"$OUT" \
   && ! grep -q "illegal option -- V" <<<"$OUT"; then
  ok "K32 BSD-style sort: sccache 0.14.0 gate passed without invoking sort -V"
else
  bad "K32 (out='${OUT//$'\n'/ }')"
fi

echo "=== K33: without timeout, the metadata probe skips immediately and fails open ==="
NO_TIMEOUT_BIN="$WORK/no-timeout-bin"; mkdir -p "$NO_TIMEOUT_BIN"
for t in bash cat cut date env git grep jq mkdir sha256sum sleep sort tail tee tr xargs; do
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
   && [ "$AFTER" = "$((BEFORE + 1))" ] && [ "$RC" = 0 ] \
   && grep -q "isolation skipped (timeout unavailable)" <<<"$OUT"; then
  ok "K33 timeout absent: metadata was not invoked and cargo ran fail-open in ${elapsed}s"
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

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
