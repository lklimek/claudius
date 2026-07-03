#!/usr/bin/env bash
# Post a reply to an inline review comment thread on a pull request.
#
# Usage: gh-post-review-reply.sh <owner/repo> <pr_number> <comment_id> <body_file>
#
#   comment_id: databaseId of the thread's first comment (the one being replied to).
#   body_file:  path to a file whose contents become the reply body (Markdown).
#
# The body is read from a file via `-F body=@file` (capital F) so gh reads the
# file and type-detects — `-f body=@file` would post the literal string "@file".
# Output: the new reply comment's html_url.
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./gh-common.sh
source "$SCRIPT_DIR/gh-common.sh"

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number> <comment_id> <body_file>" >&2
  exit 1
fi

owner_repo="$1"
pr_number="$2"
comment_id="$3"
body_file="$4"

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

if ! [[ "$comment_id" =~ ^[0-9]+$ ]]; then
  echo "Error: comment_id must be a numeric databaseId" >&2
  exit 1
fi

if [[ ! -f "$body_file" ]]; then
  echo "Error: file not found: $body_file" >&2
  exit 1
fi

# -F body=@file reads the file; -f would send the literal "@file" string.
# </dev/null keeps run_gh's stdin buffering from blocking — the body comes from
# the file, not stdin.
run_gh api "repos/${owner}/${repo}/pulls/${pr_number}/comments/${comment_id}/replies" \
  --method POST -F body=@"$body_file" --jq '.html_url' </dev/null
