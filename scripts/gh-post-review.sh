#!/usr/bin/env bash
# Post a draft review with inline comments on a pull request.
#
# Usage: gh-post-review.sh <owner> <repo> <pr_number> <json_file>
#
# The json_file must contain a JSON object with commit_id, body, and comments array.
# The script enforces draft mode by stripping any "event" field from the input.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <owner> <repo> <pr_number> <json_file>" >&2
  exit 1
fi

owner="$1"
repo="$2"
pr_number="$3"
json_file="$4"

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

echo "$cleaned" | gh api "repos/${owner}/${repo}/pulls/${pr_number}/reviews" \
  --method POST --input - --jq '.html_url'
