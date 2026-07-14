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
COUNTER="$WORK/counter"; echo 0 > "$COUNTER"; export COUNTER

# Stub cargo: count real invocations, emit an identifiable line. (The wrapper's
# own cargo-metadata resolution is a hook concern; this stub only needs `run`.)
# STUB_SLEEP fakes a real compile's wall clock, STUB_RC its verdict — both default
# to the fast/green stub the key-logic cases (K1-K6) rely on.
STUBDIR="$WORK/bin"; mkdir -p "$STUBDIR"
cat > "$STUBDIR/cargo" <<'EOF'
#!/usr/bin/env bash
n=$(cat "$COUNTER" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$COUNTER"
echo "STUB CARGO INVOCATION $n: $*"
[ "${STUB_SLEEP:-0}" != 0 ] && sleep "${STUB_SLEEP}"
exit "${STUB_RC:-0}"
EOF
chmod +x "$STUBDIR/cargo"

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

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
