#!/usr/bin/env bash
# Unit test: cargo-discipline.sh PreToolUse gate must FAIL OPEN.
#
# The DELIBERATE MIRROR of test_block_github_writes.sh: that hook guards a real
# capability and fails CLOSED (missing jq -> DENY); this hook is an efficiency
# gate and fails OPEN (missing jq -> ALLOW). Both stances are intentional — see
# D1 below, which contrasts explicitly with block-github's C15.
#
#   D0  non-cargo command                       -> ALLOW (fast path)
#   D1  cargo check + jq absent from PATH        -> ALLOW (fail-open, vs C15 deny)
#   D2  bare `cargo check`                       -> DENY  (Rule 1)
#   D3  `cargo +stable check` (toolchain)        -> DENY  (Rule 1, toolchain form)
#   D4  CLAUDIUS_FORCE=1 cargo check             -> ALLOW (escape hatch)
#   D5  `cargo build && cargo test` (chained)    -> DENY  (Rule 2)
#   D6  `cargo fmt && cargo build`               -> ALLOW (fmt does not compile)
#   D7  target-dir override == canonical         -> ALLOW (Rule 3, matches)
#   D8  target-dir override != canonical         -> DENY  (Rule 3, differs)
#   D9  raw `cargo test`                         -> DENY  (Rule 4, route to wrapper)
#   D10 `scripts/cargo-cached.sh test`           -> ALLOW (Rule 4, via wrapper)
#   D11 `cargo fmt` alone                        -> ALLOW (not a compiling cmd)
#   D12 `cargo audit` alone                      -> ALLOW (not matched)
#   D13 commit message mentioning "cargo test"   -> ALLOW (data, not an invocation)
#   D14 echoed string mentioning "cargo check"   -> ALLOW (data, not an invocation)
#   D15 quoted CARGO_TARGET_DIR mention          -> ALLOW (Rule 3 must scan $scan too)
#   D16 CLAUDIUS_ISOLATE_TARGET=1 + override, `cargo build` (Rule 4 N/A)
#                                                 -> ALLOW (scoped hatch clears Rule 3 only)
#   D17 CLAUDIUS_ISOLATE_TARGET=1 + override, raw `cargo test` (not via wrapper)
#                                                 -> DENY  (scoped hatch does NOT clear Rule 4)
#   D18 CLAUDIUS_ISOLATE_TARGET=1 + override, wrapper-routed `cargo test`
#                                                 -> ALLOW (Rule 3 cleared, Rule 4 satisfied)
#   D19 CLAUDIUS_ISOLATE_TARGET=1, no override, bare `cargo check`
#                                                 -> DENY  (scoped hatch does NOT clear Rule 1)
#
# Fully isolated: no repo state touched, all input on stdin.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="${HOOK:-$SCRIPT_DIR/../hooks/cargo-discipline.sh}"
BASHBIN="$(command -v bash)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

# A stub `cargo` whose `metadata` subcommand reports a fixed canonical target dir,
# so Rule 3's dynamic resolution is deterministic under test. Placed first on PATH.
CANON="/canonical/shared/target"
STUBDIR="$(mktemp -d)"
trap 'rm -rf "$STUBDIR"' EXIT
cat > "$STUBDIR/cargo" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "metadata" ]; then
  printf '{"target_directory":"%s"}\n' "$CANON"
  exit 0
fi
exit 0
EOF
chmod +x "$STUBDIR/cargo"
STUB_PATH="$STUBDIR:$PATH"

# Run the hook. $2 optional PATH override. Sets OUT (stdout) and RC (exit).
run_hook() {
  local stdin="$1" pathval="${2-}"
  if [ -n "$pathval" ]; then
    OUT=$(printf '%s' "$stdin" | env PATH="$pathval" "$BASHBIN" "$HOOK" 2>/dev/null); RC=$?
  else
    OUT=$(printf '%s' "$stdin" | "$BASHBIN" "$HOOK" 2>/dev/null); RC=$?
  fi
}

is_deny() { grep -Eq '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"' <<<"$OUT"; }

assert_deny() {  # $1=desc $2=stdin $3=optional-PATH
  run_hook "$2" "${3-}"
  if is_deny && [ "$RC" -eq 0 ]; then ok "$1"; else bad "$1 (rc=$RC out='${OUT//$'\n'/ }')"; fi
}
assert_allow() {  # $1=desc $2=stdin $3=optional-PATH
  run_hook "$2" "${3-}"
  if ! is_deny && [ "$RC" -eq 0 ]; then ok "$1"; else bad "$1 (rc=$RC out='${OUT//$'\n'/ }')"; fi
}

# Build a PreToolUse Bash payload with the given command string (JSON-escaped via jq).
payload() { jq -cn --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }

echo "=== fast path + fail-open (mirror of block-github fail-closed) ==="
assert_allow "D0 non-cargo command allowed"                "$(payload 'ls -la /tmp')"
# Contrast with block-github's C15: there missing jq DENIES; here it ALLOWS.
FAKEBIN="$(mktemp -d)"; trap 'rm -rf "$STUBDIR" "$FAKEBIN"' EXIT
ln -s "$(command -v cat)" "$FAKEBIN/cat" 2>/dev/null || true
assert_allow "D1 cargo check + jq absent allowed (fail-open)" "$(payload 'cargo check')" "$FAKEBIN"
echo ""

echo "=== Rule 1: cargo check banned ==="
assert_deny  "D2 bare cargo check denied"                   "$(payload 'cargo check')"
assert_deny  "D3 cargo +stable check (toolchain) denied"    "$(payload 'cargo +stable check --all-targets')"
assert_allow "D4 CLAUDIUS_FORCE=1 cargo check allowed"      "$(payload 'CLAUDIUS_FORCE=1 cargo check')"
echo ""

echo "=== Rule 2: no chained compiling commands ==="
assert_deny  "D5 cargo build && cargo test denied"          "$(payload 'cargo build && cargo test')"
assert_allow "D6 cargo fmt && cargo build allowed"          "$(payload 'cargo fmt && cargo build')"
echo ""

echo "=== Rule 3: target-dir override vs resolved canonical ==="
assert_allow "D7 override == canonical allowed" \
  "$(payload "CARGO_TARGET_DIR=$CANON cargo build")" "$STUB_PATH"
assert_deny  "D8 override != canonical denied" \
  "$(payload 'CARGO_TARGET_DIR=/some/adhoc/dir cargo build')" "$STUB_PATH"
echo ""

echo "=== Rule 3 scoped escape hatch: CLAUDIUS_ISOLATE_TARGET=1 clears Rule 3 only ==="
assert_allow "D16 CLAUDIUS_ISOLATE_TARGET=1 + override, cargo build allowed" \
  "$(payload 'CARGO_TARGET_DIR=/some/adhoc/dir CLAUDIUS_ISOLATE_TARGET=1 cargo build')" "$STUB_PATH"
assert_deny  "D17 CLAUDIUS_ISOLATE_TARGET=1 + override, raw cargo test still denied (Rule 4)" \
  "$(payload 'CARGO_TARGET_DIR=/some/adhoc/dir CLAUDIUS_ISOLATE_TARGET=1 cargo test -p foo')" "$STUB_PATH"
assert_allow "D18 CLAUDIUS_ISOLATE_TARGET=1 + override, wrapper-routed test allowed" \
  "$(payload 'CARGO_TARGET_DIR=/some/adhoc/dir CLAUDIUS_ISOLATE_TARGET=1 bash scripts/cargo-cached.sh test -p foo')" "$STUB_PATH"
assert_deny  "D19 CLAUDIUS_ISOLATE_TARGET=1, no override, bare cargo check still denied (Rule 1)" \
  "$(payload 'CLAUDIUS_ISOLATE_TARGET=1 cargo check')"
echo ""

echo "=== Rule 4: route compiling invocations through the wrapper ==="
assert_deny  "D9 raw cargo test denied"                     "$(payload 'cargo test -p foo')"
assert_allow "D10 scripts/cargo-cached.sh test allowed"     "$(payload 'bash scripts/cargo-cached.sh test -p foo')"
echo ""

echo "=== non-compiling cargo subcommands pass through ==="
assert_allow "D11 cargo fmt alone allowed"                  "$(payload 'cargo fmt')"
assert_allow "D12 cargo audit alone allowed"                "$(payload 'cargo audit')"
echo ""

echo "=== quoted mentions are data, not invocations (false-positive guard) ==="
assert_allow "D13 commit message mentioning cargo test allowed" \
  "$(payload 'git commit -m "fix: cargo test now passes"')"
assert_allow "D14 echoed string mentioning cargo check allowed" \
  "$(payload 'echo "remember: never run cargo check directly"')"
assert_allow "D15 quoted CARGO_TARGET_DIR mention allowed (Rule 3 false-positive guard)" \
  "$(payload 'git commit -m "note: cargo ignores ad-hoc CARGO_TARGET_DIR=/tmp/adhoc overrides"')" "$STUB_PATH"
echo ""

echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
