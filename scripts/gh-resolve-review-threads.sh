#!/usr/bin/env bash
# Resolve one or more review threads by their GraphQL node IDs.
#
# Usage: gh-resolve-review-threads.sh <thread_id> [thread_id ...]
#
# Thread IDs are GraphQL node IDs from gh-list-review-threads.sh output.
# All threads are resolved in a single GraphQL call using aliased mutations.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <thread_id> [thread_id ...]" >&2
  exit 1
fi

# Validate all IDs before making the API call
for id in "$@"; do
  if ! [[ "$id" =~ ^[A-Za-z0-9_=/-]+$ ]]; then
    echo "Error: invalid thread_id format: $id" >&2
    exit 1
  fi
done

# Build a single mutation with aliased fields
query="mutation {"
i=0
for id in "$@"; do
  query+=" t${i}: resolveReviewThread(input: {threadId: \"${id}\"}) { thread { isResolved } }"
  ((i++))
done
query+=" }"

ghsudo gh api graphql -f query="$query"
