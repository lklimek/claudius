#!/usr/bin/env bash
# Request one or more reviewers on a pull request.
#
# Usage: gh-request-reviewer.sh <owner/repo> <pr_number> <reviewer> [reviewer ...]
#
# Supports GitHub usernames, [bot] accounts, and @copilot (requires gh >= 2.88.0).
# Uses `gh pr edit --add-reviewer` for all reviewer types.
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number> <reviewer> [reviewer ...]" >&2
  exit 1
fi

owner_repo="$1"
pr_number="$2"
shift 2

if ! [[ "$owner_repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Error: invalid owner/repo format (expected: owner/repo)" >&2
  exit 1
fi

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

# Validate all reviewers before making the API call
# Allowed: GitHub usernames, [bot] suffix, @copilot
for reviewer in "$@"; do
  if [[ "$reviewer" == "@copilot" ]]; then
    continue
  fi
  if ! [[ "$reviewer" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\[bot\])?$ ]]; then
    echo "Error: invalid reviewer format: $reviewer" >&2
    exit 1
  fi
done

# Join reviewers with commas for gh pr edit
reviewers=$(IFS=,; echo "$*")

gh pr edit "${owner_repo}#${pr_number}" --add-reviewer "$reviewers"
