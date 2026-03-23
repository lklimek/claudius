#!/usr/bin/env bash
# List review threads for a pull request via GraphQL.
#
# Usage: gh-list-review-threads.sh <owner/repo> <pr_number>
#
# Output: JSON with thread id, isResolved, isOutdated, and first comment's databaseId, path, body, author
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

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

gh api graphql \
  -F owner="$owner" \
  -F repo="$repo" \
  -F pr_number="$pr_number" \
  -f query='
    query($owner: String!, $repo: String!, $pr_number: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr_number) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              isOutdated
              comments(first: 1) {
                nodes { databaseId path body author { login } }
              }
            }
          }
        }
      }
    }'
