#!/usr/bin/env bash
# Shared helpers for gh-*.sh wrapper scripts (gh-list-review-threads.sh,
# gh-resolve-review-threads.sh, gh-post-review.sh). Source this file; it only
# defines functions — it does not set shell options or traps, since every
# caller already does that before sourcing.

# Run `gh "$@"`, retrying once via `ghsudo gh` on 403/404/permission errors.
# Buffers piped stdin once so a ghsudo retry replays the SAME payload instead
# of reading an already-drained pipe (EOF -> silent empty request body). Skips
# buffering when stdin is a TTY: the caller isn't piping data, so keep the
# plain invocation.
run_gh() {
  local buffered="" has_stdin=0
  if [ ! -t 0 ]; then
    buffered=$(cat); has_stdin=1
  fi
  if [ "$has_stdin" -eq 1 ]; then
    if output=$(printf '%s' "$buffered" | gh "$@" 2>&1); then echo "$output"; return 0; fi
  else
    if output=$(gh "$@" 2>&1); then echo "$output"; return 0; fi
  fi
  if command -v ghsudo >/dev/null 2>&1 && echo "$output" | grep -qiE '403|404|Resource not accessible'; then
    if [ "$has_stdin" -eq 1 ]; then
      printf '%s' "$buffered" | ghsudo gh "$@"
    else
      ghsudo gh "$@"
    fi
  else
    echo "$output" >&2
    return 1
  fi
}

# GraphQL query for one page of a PR's reviewThreads, parameterized by how
# many comments to request per thread. gh-list-review-threads.sh only ever
# needs the head comment (comments_first=1, per its documented "first
# comment's ..." output contract); gh-resolve-review-threads.sh needs
# comments_first=100 because its REST/numeric --id matching checks EVERY
# comment's databaseId, not just the head (review replies have their own).
_review_threads_query() {
  local comments_first="$1"
  local query='
    query($owner: String!, $repo: String!, $pr_number: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr_number) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              isResolved
              isOutdated
              comments(first: COMMENTS_FIRST) {
                nodes { databaseId path body author { login } }
              }
            }
          }
        }
      }
    }'
  printf '%s' "${query/COMMENTS_FIRST/$comments_first}"
}

# Walk reviewThreads pageInfo cursors for a PR, accumulating every page into
# the {data:{repository:{pullRequest:{reviewThreads:{nodes:[...]}}}}} shape
# callers already consume. Hard-caps at PAGE_LIMIT pages (5000 threads at
# first:100/page) to stay defensive.
#
# Usage: fetch_all_review_threads <owner> <repo> <pr_number> <comments_first> <use_run_gh>
#   comments_first: comments(first: N) per thread — see _review_threads_query.
#   use_run_gh: "1" routes requests through run_gh (ghsudo retry on 403/404);
#     "0" uses plain gh. Each existing caller keeps its own prior choice here
#     (gh-list-review-threads.sh: "0"; gh-resolve-review-threads.sh: "1") so
#     extracting this function changes no external behavior.
fetch_all_review_threads() {
  local owner="$1" repo="$2" pr_number="$3" comments_first="$4" use_run_gh="$5"
  local PAGE_LIMIT=50
  local cursor="null"
  local pages=0
  local accumulated="[]"
  local resp nodes_chunk has_next end_cursor cursor_arg

  while :; do
    if [[ "$cursor" == "null" ]]; then
      cursor_arg=()
    else
      cursor_arg=(-f cursor="$cursor")
    fi

    if [[ "$use_run_gh" == "1" ]]; then
      resp=$(run_gh api graphql \
        -F owner="$owner" -F repo="$repo" -F pr_number="$pr_number" \
        "${cursor_arg[@]}" -f query="$(_review_threads_query "$comments_first")")
    else
      resp=$(gh api graphql \
        -F owner="$owner" -F repo="$repo" -F pr_number="$pr_number" \
        "${cursor_arg[@]}" -f query="$(_review_threads_query "$comments_first")")
    fi

    nodes_chunk=$(echo "$resp" | jq -c '.data.repository.pullRequest.reviewThreads.nodes')
    accumulated=$(jq -c -n --argjson a "$accumulated" --argjson b "$nodes_chunk" '$a + $b')

    has_next=$(echo "$resp" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')
    end_cursor=$(echo "$resp" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')

    pages=$((pages + 1))
    if [[ "$has_next" != "true" ]]; then
      break
    fi
    if [[ $pages -ge $PAGE_LIMIT ]]; then
      echo "Error: reviewThreads pagination exceeded $PAGE_LIMIT pages on $owner/$repo#$pr_number" >&2
      return 1
    fi
    cursor="$end_cursor"
  done

  jq -c -n --argjson nodes "$accumulated" \
    '{data: {repository: {pullRequest: {reviewThreads: {nodes: $nodes}}}}}'
}
