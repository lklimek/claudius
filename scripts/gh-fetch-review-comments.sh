#!/usr/bin/env bash
# Fetch all inline review comments for a pull request.
#
# Usage: gh-fetch-review-comments.sh <owner/repo> <pr_number>
#
# Output: JSON array of inline comments and replies, including round/commit provenance.
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

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

if ! [[ "$pr_number" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

gh api "repos/${owner}/${repo}/pulls/${pr_number}/comments" --paginate --slurp \
  | jq '[.[][] | {id, path, line, original_line, body, user: .user.login, in_reply_to_id, html_url, created_at, commit_id, pull_request_review_id}]'
