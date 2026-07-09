#!/usr/bin/env bash
# Regression test: gh-common.sh's fetch_all_review_threads() must page identically
# to the two loops it replaced (gh-list-review-threads.sh's inline loop and
# gh-resolve-review-threads.sh's fetch_all_threads()), and must keep each
# caller's own comments(first: N) count and run_gh/plain-gh routing — the two
# pre-extraction copies had already drifted on both.
#
# Mock `gh api graphql` returns a 2-page reviewThreads response (3 threads
# total across pages, keyed off the cursor arg) so we can assert the merge is
# correct and that each caller still requests its own comments(first: N).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GH_COMMON="$REPO_ROOT/scripts/gh-common.sh"
LIST_SCRIPT="$REPO_ROOT/scripts/gh-list-review-threads.sh"
RESOLVE_SCRIPT="$REPO_ROOT/scripts/gh-resolve-review-threads.sh"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  echo "SKIP jq not installed; cannot exercise pagination"; exit 0
fi

BASE="$(mktemp -d "${TMPDIR:-/tmp}/gh-pagination-XXXXXX")"
trap 'rm -rf "$BASE"' EXIT

# --- 2-page mock: page 1 (no cursor) has 2 nodes + hasNextPage; page 2
# (cursor=CURSOR1) has 1 more node + hasNextPage=false. A mutation query gets
# a canned "all resolved" response. ------------------------------------------
mk_paged_gh() {
  local bindir="$1" capdir="$2"
  mkdir -p "$bindir" "$capdir"
  cat > "$bindir/gh" <<CAP
#!/usr/bin/env bash
args="\$*"
printf '%s\n' "\$args" >> "$capdir/args.log"
for a in "\$@"; do
  case "\$a" in
    query=*) printf '%s\n---\n' "\${a#query=}" >> "$capdir/queries.log" ;;
  esac
done
if [[ "\$args" == *"mutation {"* ]]; then
  echo '{"data":{"t0":{"thread":{"isResolved":true}},"t1":{"thread":{"isResolved":true}},"t2":{"thread":{"isResolved":true}}}}'
elif [[ "\$args" == *"cursor=CURSOR1"* ]]; then
  cat <<'JSON'
{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"id":"t3","isResolved":false,"isOutdated":false,"comments":{"nodes":[{"databaseId":3,"path":"c.txt","body":"c","author":{"login":"bob"}}]}}]}}}}}
JSON
else
  cat <<'JSON'
{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":true,"endCursor":"CURSOR1"},"nodes":[{"id":"t1","isResolved":false,"isOutdated":false,"comments":{"nodes":[{"databaseId":1,"path":"a.txt","body":"a","author":{"login":"alice"}}]}},{"id":"t2","isResolved":false,"isOutdated":false,"comments":{"nodes":[{"databaseId":2,"path":"b.txt","body":"b","author":{"login":"alice"}}]}}]}}}}}
JSON
fi
CAP
  chmod +x "$bindir/gh"
}

echo "=== fetch_all_review_threads: 2-page merge (function level) ==="
BIN1="$BASE/bin1"; CAP1="$BASE/cap1"
mk_paged_gh "$BIN1" "$CAP1"
out=$(PATH="$BIN1:$PATH" bash -c '
  set -euo pipefail
  source "$1"
  fetch_all_review_threads owner repo 42 1 0
' _ "$GH_COMMON")

ids=$(echo "$out" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[].id' | paste -sd, -)
if [ "$ids" = "t1,t2,t3" ]; then ok "3 nodes across 2 pages merged in order (t1,t2,t3)"
else bad "expected t1,t2,t3, got: $ids"; fi

if grep -q 'comments(first: 1)' "$CAP1/queries.log" 2>/dev/null; then
  ok "comments_first=1 reached the query (list-script contract)"
else bad "comments(first: 1) not found in captured queries"; fi

if [ ! -f "$CAP1/ghsudo.log" ] && ! grep -q ghsudo "$CAP1/args.log" 2>/dev/null; then
  ok "use_run_gh=0 never touches ghsudo"
else bad "ghsudo was invoked despite use_run_gh=0"; fi

echo "=== fetch_all_review_threads: comments_first=100 (resolve-script contract) ==="
BIN2="$BASE/bin2"; CAP2="$BASE/cap2"
mk_paged_gh "$BIN2" "$CAP2"
out2=$(PATH="$BIN2:$PATH" bash -c '
  set -euo pipefail
  source "$1"
  fetch_all_review_threads owner repo 42 100 1
' _ "$GH_COMMON")

if echo "$out2" | jq -e '.data.repository.pullRequest.reviewThreads.nodes | length == 3' >/dev/null; then
  ok "comments_first=100 path still merges all 3 nodes"
else bad "node count wrong for comments_first=100 path"; fi

if grep -q 'comments(first: 100)' "$CAP2/queries.log" 2>/dev/null; then
  ok "comments_first=100 reached the query (resolve-script contract)"
else bad "comments(first: 100) not found in captured queries"; fi

echo "=== fetch_all_review_threads: use_run_gh routing ==="
BIN3="$BASE/bin3"; CAP3="$BASE/cap3"
mkdir -p "$BIN3" "$CAP3"
cat > "$BIN3/gh" <<CAP
#!/usr/bin/env bash
echo "gh: HTTP 403: Resource not accessible by integration" >&2
exit 1
CAP
cat > "$BIN3/ghsudo" <<CAP
#!/usr/bin/env bash
shift
echo "called" >> "$CAP3/ghsudo.log"
echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
CAP
chmod +x "$BIN3/gh" "$BIN3/ghsudo"

if PATH="$BIN3:$PATH" bash -c '
  set -euo pipefail
  source "$1"
  fetch_all_review_threads owner repo 42 1 1
' _ "$GH_COMMON" >/dev/null 2>&1; then
  if [ -f "$CAP3/ghsudo.log" ]; then ok "use_run_gh=1 retries via ghsudo on 403"
  else bad "use_run_gh=1 succeeded but ghsudo was never called"; fi
else bad "use_run_gh=1 should have recovered via ghsudo but the call failed"
fi

rm -f "$CAP3/ghsudo.log"
if PATH="$BIN3:$PATH" bash -c '
  set -euo pipefail
  source "$1"
  fetch_all_review_threads owner repo 42 1 0
' _ "$GH_COMMON" >/dev/null 2>&1; then
  bad "use_run_gh=0 should fail on a bare gh 403 (no fallback), but it succeeded"
else
  if [ ! -f "$CAP3/ghsudo.log" ]; then ok "use_run_gh=0 fails closed on 403 without ever calling ghsudo"
  else bad "use_run_gh=0 called ghsudo despite no fallback being requested"; fi
fi

echo "=== gh-list-review-threads.sh: end-to-end pagination unchanged ==="
BIN4="$BASE/bin4"; CAP4="$BASE/cap4"
mk_paged_gh "$BIN4" "$CAP4"
list_out=$(PATH="$BIN4:$PATH" bash "$LIST_SCRIPT" owner/repo 42)
list_ids=$(echo "$list_out" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[].id' | paste -sd, -)
if [ "$list_ids" = "t1,t2,t3" ]; then ok "gh-list-review-threads.sh still merges 2 pages into 3 threads"
else bad "gh-list-review-threads.sh pagination broke: got $list_ids"; fi
if [ ! -f "$CAP4/ghsudo.log" ]; then ok "gh-list-review-threads.sh still never calls ghsudo"
else bad "gh-list-review-threads.sh unexpectedly called ghsudo"; fi

echo "=== gh-resolve-review-threads.sh --all: end-to-end pagination unchanged ==="
BIN5="$BASE/bin5"; CAP5="$BASE/cap5"
mk_paged_gh "$BIN5" "$CAP5"
resolve_err="$BASE/resolve.err"
if PATH="$BIN5:$PATH" bash "$RESOLVE_SCRIPT" owner/repo 42 --all >/dev/null 2>"$resolve_err"; then
  if grep -q "Resolving 3 thread(s)" "$resolve_err"; then
    ok "gh-resolve-review-threads.sh --all still resolves all 3 threads across 2 pages"
  else bad "unexpected thread count: $(cat "$resolve_err")"; fi
else
  bad "gh-resolve-review-threads.sh --all failed: $(cat "$resolve_err")"
fi
if grep -q 'comments(first: 100)' "$CAP5/queries.log" 2>/dev/null; then
  ok "gh-resolve-review-threads.sh still fetches comments(first: 100)"
else bad "comments(first: 100) not found for gh-resolve-review-threads.sh"; fi

echo "=== fetch_all_review_threads: large payload does not hit ARG_MAX (regression) ==="
# Regression guard for the bug this repo's TODO tracker flagged: accumulating
# pages into a shell variable and passing it via `jq --argjson` blows past
# Linux's per-argument execve limit (MAX_ARG_STRLEN, 128 KiB) on PRs with many
# threads / long comment bodies, failing with "Argument list too long" and
# silently resolving/listing zero threads. 60 threads x ~6KB bodies (~360KB)
# comfortably exceeds that limit; the file-based merge must not care.
BIN6="$BASE/bin6"; mkdir -p "$BIN6"
cat > "$BIN6/gh" <<'CAP'
#!/usr/bin/env bash
args="$*"
if [[ "$args" == *"cursor=CURSOR1"* ]]; then
  echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
else
  jq -nc --arg body "$(head -c 6000 /dev/zero | tr '\0' 'x')" '
    { data: { repository: { pullRequest: { reviewThreads: {
        pageInfo: { hasNextPage: true, endCursor: "CURSOR1" },
        nodes: [ range(60) | { id: ("t" + (. | tostring)), isResolved: false, isOutdated: false,
                                comments: { nodes: [ { databaseId: ., path: "f.txt", body: $body, author: { login: "bob" } } ] } } ]
      } } } } }'
fi
CAP
chmod +x "$BIN6/gh"

argmax_err="$BASE/argmax.err"
if out6=$(PATH="$BIN6:$PATH" bash -c '
  set -euo pipefail
  source "$1"
  fetch_all_review_threads owner repo 42 100 0
' _ "$GH_COMMON" 2>"$argmax_err"); then
  n=$(echo "$out6" | jq '.data.repository.pullRequest.reviewThreads.nodes | length')
  if [ "$n" = "60" ]; then ok "large payload (~360KB of comment bodies) merged without hitting ARG_MAX"
  else bad "expected 60 nodes in large-payload merge, got $n"; fi
else
  bad "fetch_all_review_threads failed on large payload: $(cat "$argmax_err")"
fi

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
