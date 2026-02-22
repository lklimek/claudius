#!/usr/bin/env bash
# Get the base commit SHA for a pull request.
#
# Usage: gh-pr-base-sha.sh <owner> <repo> <pr_number>
#
# Output: the base SHA (single line)
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <owner> <repo> <pr_number>" >&2
  exit 1
fi

owner="$1"
repo="$2"
pr_number="$3"

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

gh api "repos/${owner}/${repo}/pulls/${pr_number}" --jq '.base.sha'
