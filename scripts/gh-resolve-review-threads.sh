#!/usr/bin/env bash
# Resolve review threads for a pull request with optional filtering.
#
# Enhanced mode (recommended):
#   gh-resolve-review-threads.sh <owner/repo> <pr_number> [filters_or_ids...]
#
#   Filters (combine any):
#     --outdated          Only resolve threads on outdated diffs
#     --path <glob>       Only resolve threads matching file path glob (repeatable)
#     --author <login>    Only resolve threads by this comment author (repeatable)
#     --all               Resolve ALL unresolved threads (no filter)
#     --id <thread_id>    Resolve a specific thread by ID (repeatable). Accepts:
#                           - GraphQL node IDs:      PRRT_kwDO...  / PR_kw...
#                           - REST review-comment:   discussion_r123456789
#                           - Numeric databaseId:    123456789
#                         REST/numeric IDs are auto-converted to thread node IDs
#                         using the PR context. Mix any formats freely.
#
# Legacy mode (backward-compatible):
#   gh-resolve-review-threads.sh <thread_id> [thread_id ...]
#
#   Thread IDs MUST be GraphQL node IDs (PRRT_kwDO...) when no PR context is
#   available. For discussion_r* / numeric IDs, use enhanced mode with --id.
#
# In enhanced mode, lists unresolved threads via GraphQL, applies filters,
# resolves --id selections (after format normalization), and resolves matching
# threads in a single batched mutation.
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

# Returns 0 if the given ID looks like a GraphQL review-thread node ID.
is_graphql_node_id() {
  [[ "$1" =~ ^(PRRT_|PR_kw) ]]
}

# Returns 0 if the given ID looks like a REST review-comment id (discussion_rNNN
# or bare numeric NNN). Both forms map to the comment's databaseId.
is_rest_comment_id() {
  [[ "$1" =~ ^discussion_r[0-9]+$ ]] || [[ "$1" =~ ^[0-9]+$ ]]
}

# Extract the numeric databaseId from a REST review-comment id.
extract_database_id() {
  local id="$1"
  if [[ "$id" =~ ^discussion_r([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "$id"
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
  echo "Usage: $0 <owner/repo> <pr_number> [--outdated] [--path <glob>] [--author <login>] [--all] [--id <thread_id>]" >&2
  echo "       $0 <thread_id> [thread_id ...]  (legacy mode, GraphQL node IDs only)" >&2
  exit 1
fi

if ! is_enhanced_mode "$@"; then
  # Legacy mode — only PRRT_/PR_kw GraphQL node IDs are valid here because we
  # have no PR context to convert REST/numeric IDs.
  for id in "$@"; do
    if is_rest_comment_id "$id"; then
      echo "Error: '$id' looks like a REST comment id (discussion_r* or numeric)." >&2
      echo "       Legacy mode cannot convert without PR context. Use:" >&2
      echo "       $0 <owner/repo> <pr_number> --id $id" >&2
      exit 1
    fi
    if ! is_graphql_node_id "$id"; then
      echo "Error: '$id' is not a recognized thread ID format." >&2
      echo "       Expected GraphQL node ID (PRRT_*/PR_kw*) in legacy mode." >&2
      exit 1
    fi
  done
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
declare -a explicit_ids=()

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
    --id)
      [[ $# -lt 2 ]] && { echo "Error: --id requires an argument" >&2; exit 1; }
      explicit_ids+=("$2")
      shift 2
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# Require at least one filter or --id to prevent accidental mass-resolve
if ! $filter_outdated && ! $filter_all \
    && [[ ${#filter_paths[@]} -eq 0 ]] \
    && [[ ${#filter_authors[@]} -eq 0 ]] \
    && [[ ${#explicit_ids[@]} -eq 0 ]]; then
  echo "Error: specify at least one filter (--outdated, --path, --author, --id) or --all" >&2
  exit 1
fi

# Decide whether we need to fetch PR threads. We need them when:
#   - any filter is active, OR
#   - any --id is a REST/numeric form needing conversion
need_threads_fetch=false
if $filter_outdated || $filter_all \
    || [[ ${#filter_paths[@]} -gt 0 ]] \
    || [[ ${#filter_authors[@]} -gt 0 ]]; then
  need_threads_fetch=true
fi
for id in "${explicit_ids[@]+"${explicit_ids[@]}"}"; do
  if ! is_graphql_node_id "$id"; then
    need_threads_fetch=true
    break
  fi
done

threads_json=""
if $need_threads_fetch; then
  # TODO: paginate review threads beyond the first 100. ~all PRs we encounter
  # have far fewer; revisit if a PR exceeds this and threads silently drop.
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
fi

declare -a thread_ids=()

# Resolve --id selections first, normalizing REST/numeric IDs via the fetched
# threads JSON (databaseId match on the first comment of each thread).
for id in "${explicit_ids[@]+"${explicit_ids[@]}"}"; do
  if is_graphql_node_id "$id"; then
    thread_ids+=("$id")
    continue
  fi
  if ! is_rest_comment_id "$id"; then
    echo "Error: --id value '$id' is not a recognized thread ID format" >&2
    echo "       Expected: PRRT_*/PR_kw* (GraphQL), discussion_r<n> or numeric (REST)" >&2
    exit 1
  fi
  db_id=$(extract_database_id "$id")
  node_id=$(echo "$threads_json" | jq -r --argjson db "$db_id" \
    '.data.repository.pullRequest.reviewThreads.nodes[] | select(.comments.nodes[0].databaseId == $db) | .id' \
    | head -n1)
  if [[ -z "$node_id" || "$node_id" == "null" ]]; then
    echo "Error: could not map comment id '$id' (databaseId=$db_id) to a review thread on $owner_repo#$pr_number" >&2
    exit 1
  fi
  thread_ids+=("$node_id")
done

# Apply filter-based selection if any filter was supplied.
if $filter_outdated || $filter_all \
    || [[ ${#filter_paths[@]} -gt 0 ]] \
    || [[ ${#filter_authors[@]} -gt 0 ]]; then
  jq_filter='.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)'

  if $filter_outdated; then
    jq_filter+=' | select(.isOutdated == true)'
  fi

  if [[ ${#filter_paths[@]} -gt 0 ]]; then
    path_conditions=()
    for p in "${filter_paths[@]}"; do
      regex=$(echo "$p" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\./\\\\./g; s/\*/.*/g; s/\?/./g')
      path_conditions+=("(.comments.nodes[0].path | test(\"${regex}\"))")
    done
    combined=$(IFS=" or "; echo "${path_conditions[*]}")
    jq_filter+=" | select(${combined})"
  fi

  if [[ ${#filter_authors[@]} -gt 0 ]]; then
    author_conditions=()
    for a in "${filter_authors[@]}"; do
      escaped_a=$(echo "$a" | sed 's/\\/\\\\/g; s/"/\\"/g')
      author_conditions+=("(.comments.nodes[0].author.login == \"${escaped_a}\")")
    done
    combined=$(IFS=" or "; echo "${author_conditions[*]}")
    jq_filter+=" | select(${combined})"
  fi

  jq_filter+=' | .id'

  mapfile -t filter_ids < <(echo "$threads_json" | jq -r "$jq_filter")
  thread_ids+=("${filter_ids[@]+"${filter_ids[@]}"}")
fi

# Deduplicate while preserving order
declare -A seen=()
declare -a unique_ids=()
for id in "${thread_ids[@]+"${thread_ids[@]}"}"; do
  [[ -z "$id" ]] && continue
  if [[ -z "${seen[$id]:-}" ]]; then
    seen[$id]=1
    unique_ids+=("$id")
  fi
done

if [[ ${#unique_ids[@]} -eq 0 ]]; then
  echo "No matching unresolved threads found." >&2
  exit 0
fi

echo "Resolving ${#unique_ids[@]} thread(s)..." >&2
resolve_by_ids "${unique_ids[@]}"
