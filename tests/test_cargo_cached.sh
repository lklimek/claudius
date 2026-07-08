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
STUBDIR="$WORK/bin"; mkdir -p "$STUBDIR"
cat > "$STUBDIR/cargo" <<'EOF'
#!/usr/bin/env bash
n=$(cat "$COUNTER" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$COUNTER"
echo "STUB CARGO INVOCATION $n: $*"
exit 0
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

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
