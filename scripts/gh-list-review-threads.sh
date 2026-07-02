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

# Walk reviewThreads pageInfo cursors so PRs with >100 threads are fully listed,
# then emit the same {data:...:{reviewThreads:{nodes:[...]}}} shape callers already
# consume. Hard-cap at PAGE_LIMIT pages (5000 threads) to stay defensive.
PAGE_LIMIT=50
cursor="null"
pages=0
accumulated="[]"

while :; do
  if [[ "$cursor" == "null" ]]; then
    cursor_arg=()
  else
    cursor_arg=(-f cursor="$cursor")
  fi

  resp=$(gh api graphql \
    -F owner="$owner" \
    -F repo="$repo" \
    -F pr_number="$pr_number" \
    "${cursor_arg[@]}" \
    -f query='
      query($owner: String!, $repo: String!, $pr_number: Int!, $cursor: String) {
        repository(owner: $owner, name: $repo) {
          pullRequest(number: $pr_number) {
            reviewThreads(first: 100, after: $cursor) {
              pageInfo { hasNextPage endCursor }
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
      }')

  nodes_chunk=$(echo "$resp" | jq -c '.data.repository.pullRequest.reviewThreads.nodes')
  accumulated=$(jq -c -n --argjson a "$accumulated" --argjson b "$nodes_chunk" '$a + $b')

  has_next=$(echo "$resp" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
  end_cursor=$(echo "$resp" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')

  pages=$((pages + 1))
  if [[ "$has_next" != "true" ]]; then
    break
  fi
  if [[ $pages -ge $PAGE_LIMIT ]]; then
    echo "Error: reviewThreads pagination exceeded $PAGE_LIMIT pages on $owner_repo#$pr_number" >&2
    exit 1
  fi
  cursor="$end_cursor"
done

jq -c -n --argjson nodes "$accumulated" \
  '{data: {repository: {pullRequest: {reviewThreads: {nodes: $nodes}}}}}'
