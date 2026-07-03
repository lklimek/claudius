#!/usr/bin/env bash
# Regression test: gh-resolve-review-threads.sh --path glob -> regex escaping.
#
# The --path filter turns a shell glob into a regex embedded in jq's test("..."),
# so EVERY regex metacharacter in a filename must be escaped or it silently matches
# the wrong files. The historical bug: '[' ']' '(' ')' '+' etc. were left raw, so a
# Next.js dynamic route like 'pages/[id].tsx' compiled to a character class and
# matched ZERO files -- reported as "No matching unresolved threads found."
#
# We drive the REAL glob_to_regex (the script is source-safe), build the regex the
# same way the script does, and confirm literal metacharacter filenames match while
# glob wildcards (*, ?) still behave.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${SCRIPT:-$SCRIPT_DIR/../scripts/gh-resolve-review-threads.sh}"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass=0; fail=0
ok()  { echo -e "  ${GREEN}\xe2\x9c\x93${NC} $1"; pass=$((pass + 1)); }
bad() { echo -e "  ${RED}\xe2\x9c\x97${NC} $1"; fail=$((fail + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  echo "SKIP jq not installed; cannot exercise glob->regex matching"; exit 0
fi

# glob_to_regex, isolated in a fresh shell so the script's `set -e`/ERR trap can't
# leak into this harness. The source-guard skips the CLI logic on source.
regex_for() { bash -c 'source "$1"; glob_to_regex "$2"' _ "$SCRIPT" "$1"; }

# Reproduce the script's real consumption: embed the regex inside the jq PROGRAM
# text, where jq's parser collapses the doubled backslashes before the regex engine.
matches() {  # $1=path  $2=glob -> prints true/false
  local re; re=$(regex_for "$2")
  jq -rn --arg p "$1" "(\$p | test(\"${re}\"))"
}

check() {  # $1=desc  $2=want(true|false)  $3=path  $4=glob
  local got; got="$(matches "$3" "$4")"
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1 (want=$2 got=$got glob=$4 path=$3 regex=$(regex_for "$4"))"; fi
}

echo "=== square-bracket dynamic route (the original bug) ==="
check "pages/[id].tsx matches its literal self"       true  'pages/[id].tsx' 'pages/[id].tsx'
check "pages/[id].tsx does NOT match pages/xid.tsx"   false 'pages/xid.tsx'  'pages/[id].tsx'
check "[id] is not treated as a char class (i)"       false 'pages/i.tsx'    'pages/[id].tsx'

echo "=== parentheses (Next.js route groups) ==="
check "app/(main)/page.tsx matches literally"         true  'app/(main)/page.tsx' 'app/(main)/page.tsx'
check "(main) is not a capture group"                 false 'app/main/page.tsx'   'app/(main)/page.tsx'

echo "=== plus sign ==="
check "c++/vector.h matches literally"                true  'c++/vector.h' 'c++/vector.h'
check "'+' is not a quantifier (no c-repetition)"     false 'cccc/vector.h' 'c++/vector.h'

echo "=== other metacharacters stay literal ==="
check "brace filename matches literally"              true  'gen/{x}.ts' 'gen/{x}.ts'
check "caret/dollar/pipe filename matches literally"  true  'a^b$c|d.txt' 'a^b$c|d.txt'

echo "=== glob wildcards still work ==="
check "* expands to .* (matches)"                     true  'src/foo.ts'  'src/*.ts'
check "? matches exactly one char (match)"            true  'fileA.js'    'file?.js'
check "? does NOT match two chars"                    false 'fileAB.js'   'file?.js'
check "literal dot is not a wildcard"                 false 'srcXfoo.ts'  'src.foo.ts'

echo "=== anchoring: jq's test() is substring search, not full-match ==="
check "*.rs still matches main.rs"                    true  'main.rs'          '*.rs'
check "*.rs does NOT match main.rson (over-match)"     false 'main.rson'        '*.rs'
check "src/*.ts still matches src/a.ts"                true  'src/a.ts'         'src/*.ts'
check "src/*.ts does NOT match backup/src/a.ts (over-match)" false 'backup/src/a.ts' 'src/*.ts'

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
