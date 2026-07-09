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
# many comments to request per thread. See fetch_all_review_threads below
# for why each caller passes a different comments_first value.
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
  local resp_file="" accum_file="" new_file="" result
  local has_next end_cursor cursor_arg

  # Defined before any mktemp call (and guarded per-variable) so a failure
  # partway through the mktemp sequence below still cleans up whichever
  # temp file(s) were already created, instead of leaking them. Guarding on
  # non-empty also means a still-unset accum_file can't turn "$accum_file.next"
  # into the literal ".next" and delete an unrelated file in the caller's cwd.
  _cleanup_review_threads_tmp() {
    [[ -n "$accum_file" ]] && rm -f "$accum_file" "$accum_file.next" 2>/dev/null
    [[ -n "$new_file" ]] && rm -f "$new_file" 2>/dev/null
    [[ -n "$resp_file" ]] && rm -f "$resp_file" 2>/dev/null
  }

  # Page merging goes through temp files, never a growing shell variable: an
  # --argjson value built from accumulated JSON (all thread nodes incl. full
  # comment bodies) hits the OS ARG_MAX limit on PRs with ~75+ threads,
  # failing execve with "Argument list too long" and resolving/listing zero
  # threads. Files have no such limit — only command-line argument strings do.
  #
  # mktemp needs an explicit template: BSD/macOS mktemp has no built-in
  # default template and errors ("too few arguments") when called bare.
  local tmpl="${TMPDIR:-/tmp}/gh-threads.XXXXXX"
  if ! accum_file=$(mktemp "$tmpl") || ! new_file=$(mktemp "$tmpl") || ! resp_file=$(mktemp "$tmpl"); then
    echo "Error: mktemp failed while fetching review threads" >&2
    _cleanup_review_threads_tmp
    return 1
  fi
  printf '[]' > "$accum_file"

  while :; do
    if [[ "$cursor" == "null" ]]; then
      cursor_arg=()
    else
      cursor_arg=(-f cursor="$cursor")
    fi

    # Every gh/jq call below is explicitly checked and cleans up on failure —
    # do not rely on the caller's `set -e` alone: it doesn't fire in every
    # shell context (command substitutions, conditionals), and a caller
    # without `-e` at all would otherwise print an empty line and return
    # success on a corrupt/partial response.
    if [[ "$use_run_gh" == "1" ]]; then
      if ! run_gh api graphql \
        -F owner="$owner" -F repo="$repo" -F pr_number="$pr_number" \
        "${cursor_arg[@]}" -f query="$(_review_threads_query "$comments_first")" > "$resp_file"; then
        echo "Error: gh api graphql failed while fetching review threads on $owner/$repo#$pr_number" >&2
        _cleanup_review_threads_tmp
        return 1
      fi
    else
      if ! gh api graphql \
        -F owner="$owner" -F repo="$repo" -F pr_number="$pr_number" \
        "${cursor_arg[@]}" -f query="$(_review_threads_query "$comments_first")" > "$resp_file"; then
        echo "Error: gh api graphql failed while fetching review threads on $owner/$repo#$pr_number" >&2
        _cleanup_review_threads_tmp
        return 1
      fi
    fi

    if ! jq -c '.data.repository.pullRequest.reviewThreads.nodes' "$resp_file" > "$new_file"; then
      echo "Error: failed to parse reviewThreads response on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi
    if ! jq -c -s '.[0] + .[1]' "$accum_file" "$new_file" > "$accum_file.next"; then
      echo "Error: failed to merge reviewThreads page on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi
    if ! mv "$accum_file.next" "$accum_file"; then
      echo "Error: failed to move merged reviewThreads page into place on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi

    if ! has_next=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage' "$resp_file"); then
      echo "Error: failed to read pageInfo.hasNextPage on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi
    if ! end_cursor=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor' "$resp_file"); then
      echo "Error: failed to read pageInfo.endCursor on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi

    pages=$((pages + 1))
    if [[ "$has_next" != "true" ]]; then
      break
    fi
    if [[ $pages -ge $PAGE_LIMIT ]]; then
      echo "Error: reviewThreads pagination exceeded $PAGE_LIMIT pages on $owner/$repo#$pr_number" >&2
      _cleanup_review_threads_tmp
      return 1
    fi
    cursor="$end_cursor"
  done

  # --slurpfile reads the accumulated array from disk, not argv — the one
  # remaining --argjson-shaped value here is just the small query skeleton.
  if ! result=$(jq -c -n --slurpfile nodes "$accum_file" \
    '{data: {repository: {pullRequest: {reviewThreads: {nodes: $nodes[0]}}}}}'); then
    echo "Error: failed to assemble merged reviewThreads result on $owner/$repo#$pr_number" >&2
    _cleanup_review_threads_tmp
    return 1
  fi
  _cleanup_review_threads_tmp
  printf '%s\n' "$result"
}
