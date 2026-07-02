#!/usr/bin/env bash
# Regression test: gh-post-review.sh must not lose the review body on ghsudo retry.
#
# run_gh() posts via `printf payload | gh api --input -`. When the first `gh` fails
# with 403/404 (the routine triage-role case), it retries with `ghsudo gh`. The bug:
# the retry read from an ALREADY-DRAINED pipe -> EOF -> silently posted an EMPTY body
# while reporting success. The fix buffers the payload once and replays the SAME
# bytes to both attempts.
#
# Mock harness: `gh` records its stdin then fails 403; `ghsudo gh` records ITS stdin
# then succeeds. We assert the retry received the full, correct payload.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${SCRIPT:-$SCRIPT_DIR/../scripts/gh-post-review.sh}"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  echo "SKIP jq not installed; gh-post-review.sh needs it"; exit 0
fi

BASE="$(mktemp -d "${TMPDIR:-/tmp}/gh-post-XXXXXX")"
trap 'rm -rf "$BASE"' EXIT
export CAPDIR="$BASE/cap"; mkdir -p "$CAPDIR"
BIN="$BASE/bin"; mkdir -p "$BIN"

INPUT="$BASE/review.json"
cat > "$INPUT" <<'JSON'
{"event":"REQUEST_CHANGES","commit_id":"deadbeef","body":"Please address the findings.","comments":[{"path":"src/a.rs","line":10,"body":"nit"}]}
JSON
EXPECTED_URL="https://github.com/o/r/pull/1#pullrequestreview-777"

# --- mocks -----------------------------------------------------------------
# gh: capture stdin, fail with a 403 that run_gh's grep recognizes.
cat > "$BIN/gh" <<CAP
#!/usr/bin/env bash
cat > "\$CAPDIR/gh.stdin"
echo "gh: HTTP 403: Resource not accessible by integration" >&2
exit 1
CAP
# ghsudo gh ...: capture stdin (the retried payload), then succeed.
cat > "$BIN/ghsudo" <<CAP
#!/usr/bin/env bash
shift   # drop the leading 'gh'
cat > "\$CAPDIR/ghsudo.stdin"
printf '%s\n' "$EXPECTED_URL"
CAP
chmod +x "$BIN/gh" "$BIN/ghsudo"

OUT="$BASE/out"; ERR="$BASE/err"
PATH="$BIN:$PATH" bash "$SCRIPT" o/r 1 "$INPUT" >"$OUT" 2>"$ERR"
rc=$?

CLEANED="$BASE/cleaned.json"; jq -S 'del(.event)' "$INPUT" > "$CLEANED"

echo "=== ghsudo retry receives the full payload (the bug) ==="
if [ -s "$CAPDIR/ghsudo.stdin" ]; then ok "retry stdin is non-empty (not a drained pipe)"
else bad "retry stdin EMPTY -> would have posted a blank review"; fi

if [ -f "$CAPDIR/ghsudo.stdin" ] && diff -q <(jq -S . "$CAPDIR/ghsudo.stdin" 2>/dev/null) "$CLEANED" >/dev/null 2>&1
then ok "retry stdin equals the cleaned payload"
else bad "retry stdin != cleaned payload (got: $(cat "$CAPDIR/ghsudo.stdin" 2>/dev/null))"; fi

echo "=== both attempts see the same payload, event stripped ==="
if [ -f "$CAPDIR/gh.stdin" ] && diff -q <(jq -S . "$CAPDIR/gh.stdin" 2>/dev/null) "$CLEANED" >/dev/null 2>&1
then ok "first attempt also received the full cleaned payload"
else bad "first attempt payload wrong (got: $(cat "$CAPDIR/gh.stdin" 2>/dev/null))"; fi

if ! grep -q '"event"' "$CAPDIR/ghsudo.stdin" 2>/dev/null; then ok "draft mode enforced: no event field sent"
else bad "event field leaked into the request"; fi

echo "=== success is reported from the retry ==="
if [ "$rc" -eq 0 ] && grep -qF "$EXPECTED_URL" "$OUT"; then ok "script exits 0 and prints the html_url"
else bad "script rc=$rc out=$(cat "$OUT") err=$(cat "$ERR")"; fi

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
