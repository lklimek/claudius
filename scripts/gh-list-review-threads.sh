#!/usr/bin/env bash
# List review threads for a pull request via GraphQL.
#
# Usage: gh-list-review-threads.sh <owner/repo> <pr_number>
#
# Output: JSON with thread id, isResolved, isOutdated, and first comment's databaseId, path, body, author
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./gh-common.sh
source "$SCRIPT_DIR/gh-common.sh"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number>" >&2
  exit 1
fi

owner_repo="$1"
pr_number="$2"

if ! [[ "$owner_repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Error: invalid owner/repo format (expected: owner/repo)" >&2
  exit 1
fi

owner="${owner_repo%/*}"
repo="${owner_repo##*/}"

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

# comments_first=1, use_run_gh=0 — see fetch_all_review_threads in
# gh-common.sh for why this script uses these values.
fetch_all_review_threads "$owner" "$repo" "$pr_number" 1 0
