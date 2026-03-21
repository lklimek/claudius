#!/usr/bin/env bash
# Resolve review threads for a pull request with optional filtering.
#
# Enhanced mode (recommended):
#   gh-resolve-review-threads.sh <owner/repo> <pr_number> [filters...]
#
#   Filters (combine any):
#     --outdated          Only resolve threads on outdated diffs
#     --path <glob>       Only resolve threads matching file path glob (repeatable)
#     --author <login>    Only resolve threads by this comment author (repeatable)
#     --all               Resolve ALL unresolved threads (no filter)
#
# Legacy mode (backward-compatible):
#   gh-resolve-review-threads.sh <thread_id> [thread_id ...]
#
#   Thread IDs are GraphQL node IDs from gh-list-review-threads.sh output.
#
# In enhanced mode, lists unresolved threads via GraphQL, applies filters,
# and resolves matching threads in a single batched mutation.
set -euo pipefail
trap 'echo "Error: $0 failed at line $LINENO (exit $?)" >&2' ERR

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

resolve_by_ids() {
  local ids=("$@")
  if [[ ${#ids[@]} -eq 0 ]]; then
    echo "No threads to resolve." >&2
    return 0
  fi

  # Validate all IDs
  for id in "${ids[@]}"; do
    if ! [[ "$id" =~ ^[A-Za-z0-9_=/-]+$ ]]; then
      echo "Error: invalid thread_id format: $id" >&2
      exit 1
    fi
  done

  # Build a single mutation with aliased fields
  local query="mutation {"
  local i=0
  for id in "${ids[@]}"; do
    query+=" t${i}: resolveReviewThread(input: {threadId: \"${id}\"}) { thread { isResolved } }"
    ((i++)) || true
  done
  query+=" }"

  run_gh api graphql -f query="$query"
}

# Detect mode: legacy (first arg looks like a GraphQL ID) vs enhanced (owner/repo)
is_enhanced_mode() {
  [[ "${1:-}" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] && [[ "${2:-}" =~ ^[0-9]+$ ]]
}

# Legacy mode: direct thread IDs
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number> [--outdated] [--path <glob>] [--author <login>] [--all]" >&2
  echo "       $0 <thread_id> [thread_id ...]  (legacy mode)" >&2
  exit 1
fi

if ! is_enhanced_mode "$@"; then
  # Legacy mode
  resolve_by_ids "$@"
  exit $?
fi

# Enhanced mode
owner_repo="$1"
pr_number="$2"
shift 2

# Validate inputs (same checks as gh-list-review-threads.sh)
if ! [[ "$owner_repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Error: invalid owner/repo format (expected: owner/repo)" >&2
  exit 1
fi

if ! [[ "$pr_number" =~ ^[0-9]+$ ]]; then
  echo "Error: pr_number must be a positive integer" >&2
  exit 1
fi

owner="${owner_repo%/*}"
repo="${owner_repo##*/}"

# Parse filter flags
filter_outdated=false
filter_all=false
declare -a filter_paths=()
declare -a filter_authors=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --outdated)
      filter_outdated=true
      shift
      ;;
    --path)
      [[ $# -lt 2 ]] && { echo "Error: --path requires an argument" >&2; exit 1; }
      filter_paths+=("$2")
      shift 2
      ;;
    --author)
      [[ $# -lt 2 ]] && { echo "Error: --author requires an argument" >&2; exit 1; }
      filter_authors+=("$2")
      shift 2
      ;;
    --all)
      filter_all=true
      shift
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Require at least one filter to prevent accidental mass-resolve
if ! $filter_outdated && ! $filter_all && [[ ${#filter_paths[@]} -eq 0 ]] && [[ ${#filter_authors[@]} -eq 0 ]]; then
  echo "Error: specify at least one filter (--outdated, --path, --author) or --all" >&2
  exit 1
fi

# Fetch unresolved threads with metadata needed for filtering
threads_json=$(run_gh api graphql \
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
    }')

# Build jq filter for unresolved threads matching criteria
jq_filter='.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)'

if $filter_outdated; then
  jq_filter+=' | select(.isOutdated == true)'
fi

if [[ ${#filter_paths[@]} -gt 0 ]]; then
  # Build jq path match: any of the glob patterns
  path_conditions=()
  for p in "${filter_paths[@]}"; do
    # Convert glob to jq test pattern (simple * glob → regex)
    # Escape backslashes and quotes first, then convert glob chars
    regex=$(echo "$p" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\./\\\\./g; s/\*/.*/g; s/\?/./g')
    path_conditions+=("(.comments.nodes[0].path | test(\"${regex}\"))")
  done
  combined=$(IFS=" or "; echo "${path_conditions[*]}")
  jq_filter+=" | select(${combined})"
fi

if [[ ${#filter_authors[@]} -gt 0 ]]; then
  author_conditions=()
  for a in "${filter_authors[@]}"; do
    # Escape backslashes and quotes for safe jq string interpolation
    escaped_a=$(echo "$a" | sed 's/\\/\\\\/g; s/"/\\"/g')
    author_conditions+=("(.comments.nodes[0].author.login == \"${escaped_a}\")")
  done
  combined=$(IFS=" or "; echo "${author_conditions[*]}")
  jq_filter+=" | select(${combined})"
fi

jq_filter+=' | .id'

# Extract matching thread IDs
mapfile -t thread_ids < <(echo "$threads_json" | jq -r "$jq_filter")

if [[ ${#thread_ids[@]} -eq 0 ]]; then
  echo "No matching unresolved threads found." >&2
  exit 0
fi

echo "Resolving ${#thread_ids[@]} thread(s)..." >&2
resolve_by_ids "${thread_ids[@]}"
