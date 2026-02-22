#!/usr/bin/env bash
# Resolve a single review thread by its GraphQL node ID.
#
# Usage: gh-resolve-review-thread.sh <thread_id>
#
# The thread_id is the GraphQL node ID from gh-list-review-threads.sh output.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <thread_id>" >&2
  exit 1
fi

thread_id="$1"

gh api graphql -f query="
mutation {
  resolveReviewThread(input: {threadId: \"${thread_id}\"}) {
    thread { isResolved }
  }
}"
