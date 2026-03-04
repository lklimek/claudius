#!/usr/bin/env bash
# Post a draft review with inline comments on a pull request.
#
# Usage: gh-post-review.sh <owner/repo> <pr_number> <json_file>
#
# The json_file must contain a JSON object with commit_id, body, and comments array.
# The script enforces draft mode by stripping any "event" field from the input.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number> <json_file>" >&2
  exit 1
fi

owner_repo="$1"
pr_number="$2"
json_file="$3"

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

if [[ ! -f "$json_file" ]]; then
  echo "Error: file not found: $json_file" >&2
  exit 1
fi

# Strip "event" field to enforce draft mode — omitting it makes GitHub create
# a pending (draft) review that the user must publish manually.
cleaned=$(jq 'del(.event)' "$json_file")

echo "$cleaned" | ghsudo gh api "repos/${owner}/${repo}/pulls/${pr_number}/reviews" \
  --method POST --input - --jq '.html_url'
