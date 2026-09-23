# PR Review Operations

All operations use the `gh` CLI and the wrapper scripts at `<plugin-root>/scripts/`.

## Get PR Context

```bash
gh pr view <number> --json number,title,body,url,baseRefName,headRefName
gh pr view <number> --json files --jq '.files[] | {path, additions, deletions}'
gh pr diff <number>
```

`files` and `gh pr diff` may return large responses — see the parent skill's § Context Management for the subagent delegation pattern.

## PR-Level Comments

```bash
gh pr comment <number> --body "<markdown>"
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'
```

## Fetch Existing Reviews and Comments

Fetch before posting to avoid duplicates: drop any finding already covered by an existing review (match by file:line and substance, not exact wording).

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh <owner/repo> <pr>
# -> [{id, state, submitted_at, body, user}]

${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
# -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

${CLAUDE_SKILL_DIR}/../../scripts/gh-list-review-threads.sh <owner/repo> <pr>
# -> {id, isResolved, comments: [{databaseId, path, body}]}  (thread resolution status)
```

## Verify Lines Are Within the Diff

GitHub rejects inline comments on lines outside the diff (HTTP 422). Before posting:

1. Get the PR base SHA:
   ```bash
   ${CLAUDE_SKILL_DIR}/../../scripts/gh-pr-base-sha.sh <owner/repo> <number>
   ```

2. Check each file's diff hunks:
   ```bash
   git diff <base-sha>...HEAD -- <file> | grep "^@@"
   ```
   A hunk `@@ -old,len +new,len @@` means new-file lines `new` through `new+len-1` are in the diff.

3. If a finding's line is outside the diff, post it in the summary comment instead.

## Post a Review from report.json

For a consolidated `report.json` (`grumpy-review`), post with one command — the script handles
selection, diff-bounds mapping, open-thread dedup, off-diff findings, the event, and 422 /
rejected-APPROVE fallbacks (details: script docstring):

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/post_pr_review.py <owner/repo> <pr> <report.json> --body "<one-line verdict>" [--comments <comments.json>] [--min-severity MEDIUM] [--draft] [--dry-run]
```

- `--comments`: optional JSON `{"<final_id>": "comment text" | null}` written with the Write
  tool; omitted IDs get text built from the finding, `null` skips one.
- Without `--draft` it publishes: APPROVE when nothing is posted and no unresolved thread
  remains, else COMMENT. `--dry-run` prints the payload without posting.
- Prints `{url, event, inline, in_body, covered_by_open_threads, skipped}`.

## Post Draft Review (hand-built payload)

`gh-post-review.sh` strips `event` automatically — reviews always post as drafts:
```bash
SESSION_DIR=$(mkdir -p /tmp/claude && mktemp -d /tmp/claude/XXXXXX)
cat > "$SESSION_DIR/pr-review.json" << 'ENDJSON'
{
  "commit_id": "<SHA>",
  "body": "See summary comment for full report.\n\n<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>",
  "comments": [
    {"path": "src/file.rs", "line": 42, "side": "RIGHT", "body": "Finding here."}
  ]
}
ENDJSON
${CLAUDE_SKILL_DIR}/../../scripts/gh-post-review.sh <owner/repo> <number> "$SESSION_DIR/pr-review.json"
```

- Use `side: "RIGHT"` for new code
- Get commit SHA: `git rev-parse HEAD`

## Wrapper Scripts

```
gh-fetch-review-comments.sh <owner/repo> <pr>
  -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

gh-fetch-reviews.sh <owner/repo> <pr>
  -> [{id, state, submitted_at, body, user}]

gh-post-review.sh <owner/repo> <pr> <json_file>
  -> Posts draft review. Input: {commit_id, body, comments: [{path, line, side, body}]}

post_pr_review.py <owner/repo> <pr> <report.json> [options]
  -> Builds + posts a review from report.json (see § Post a Review from report.json).

gh-request-reviewer.sh <owner/repo> <pr> <reviewer> [reviewer ...]

gh-list-review-threads.sh <owner/repo> <pr>
  -> {id, isResolved, comments: [{databaseId, path, body}]}

gh-resolve-review-threads.sh <thread_id> [thread_id ...]
  -> Resolves PRRT_* GraphQL node IDs in a single API call. Ask user first.
gh-resolve-review-threads.sh <owner/repo> <pr> --id <id> [--id <id> ...]
  -> Same, but accepts discussion_r* and numeric databaseId — auto-converts via PR context.

gh-pr-base-sha.sh <owner/repo> <pr>
  -> Base commit SHA.

diff-anchors.py <file_path> [...]
  -> "path -> sha256". For diff URLs: ...files#diff-<SHA256>R<line>
```
