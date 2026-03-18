#!/usr/bin/env bash
# Resolve one or more review threads by their GraphQL node IDs.
#
# Usage: gh-resolve-review-threads.sh <thread_id> [thread_id ...]
#
# Thread IDs are GraphQL node IDs from gh-list-review-threads.sh output.
# All threads are resolved in a single GraphQL call using aliased mutations.
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

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

# Build a single mutation with aliased fields
query="mutation {"
i=0
for id in "$@"; do
  query+=" t${i}: resolveReviewThread(input: {threadId: \"${id}\"}) { thread { isResolved } }"
  ((i++))
done
query+=" }"

run_gh api graphql -f query="$query"
