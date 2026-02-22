#!/usr/bin/env bash
# Fetch all inline review comments for a pull request.
#
# Usage: gh-fetch-review-comments.sh <owner> <repo> <pr_number>
#
# Output: JSON objects with id, path, line, original_line, body, user, in_reply_to_id, html_url
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <owner> <repo> <pr_number>" >&2
  exit 1
fi

owner="$1"
repo="$2"
pr_number="$3"

if ! [[ "$owner" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Error: invalid owner format" >&2
  exit 1
fi

if ! [[ "$repo" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Error: invalid repo format" >&2
  exit 1
fi

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

gh api "repos/${owner}/${repo}/pulls/${pr_number}/comments" --paginate \
  --jq '.[] | {id, path, line, original_line, body, user: .user.login, in_reply_to_id, html_url}'
