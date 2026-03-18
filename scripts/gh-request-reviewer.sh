#!/usr/bin/env bash
# Request a reviewer on a pull request.
#
# Usage: gh-request-reviewer.sh <owner/repo> <pr_number> <reviewer>
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number> <reviewer>" >&2
  exit 1
fi

owner_repo="$1"
pr_number="$2"
reviewer="$3"

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

# GitHub usernames: alphanumeric and hyphens, 1-39 chars, no leading/trailing hyphen
# Also allow [bot] suffix for app accounts (e.g. "dependabot[bot]")
# Also allow @copilot (virtual reviewer, requires gh >= 2.88.0)
if [[ "$reviewer" == "@copilot" ]]; then
  gh pr edit "${owner_repo}#${pr_number}" --add-reviewer @copilot
  exit $?
fi
if ! [[ "$reviewer" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\[bot\])?$ ]]; then
  echo "Error: invalid reviewer format" >&2
  exit 1
fi

run_gh() {
  if output=$(gh "$@" 2>&1); then
    echo "$output"
  elif command -v ghsudo >/dev/null 2>&1 && echo "$output" | grep -qiE '403|404|Resource not accessible'; then
    ghsudo gh "$@"
  else
    echo "$output" >&2
    return 1
  fi
}

# NOTE: For @copilot reviews, use `gh pr edit --add-reviewer @copilot` instead
# (requires gh >= 2.88.0). The REST API does not support virtual reviewers.
run_gh api "repos/${owner}/${repo}/pulls/${pr_number}/requested_reviewers" \
  --method POST -f "reviewers[]=${reviewer}"
