#!/usr/bin/env bash
# Request a reviewer on a pull request.
#
# Usage: gh-request-reviewer.sh <owner> <repo> <pr_number> <reviewer>
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <owner> <repo> <pr_number> <reviewer>" >&2
  exit 1
fi

owner="$1"
repo="$2"
pr_number="$3"
reviewer="$4"

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

# GitHub usernames: alphanumeric and hyphens, 1-39 chars, no leading/trailing hyphen
# Also allow [bot] suffix for app accounts (e.g. "dependabot[bot]")
if ! [[ "$reviewer" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\[bot\])?$ ]]; then
  echo "Error: invalid reviewer format" >&2
  exit 1
fi

gh api "repos/${owner}/${repo}/pulls/${pr_number}/requested_reviewers" \
  --method POST -f "reviewers[]=${reviewer}"
