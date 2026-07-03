#!/usr/bin/env bash
# Get the base commit SHA for a pull request.
#
# Usage: gh-pr-base-sha.sh <owner/repo> <pr_number>
#
# Output: the base SHA (single line)
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

gh api "repos/${owner}/${repo}/pulls/${pr_number}" --jq '.base.sha'
