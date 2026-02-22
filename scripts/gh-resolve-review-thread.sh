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

# GitHub GraphQL node IDs are base64-encoded, containing only [A-Za-z0-9_=-]
if ! [[ "$thread_id" =~ ^[A-Za-z0-9_=/-]+$ ]]; then
  echo "Error: invalid thread_id format" >&2
  exit 1
fi

gh api graphql \
  -F thread_id="$thread_id" \
  -f query='
    mutation($thread_id: ID!) {
      resolveReviewThread(input: {threadId: $thread_id}) {
        thread { isResolved }
      }
    }'
