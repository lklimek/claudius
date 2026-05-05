# PR Review Operations

Prefer GitHub MCP (`mcp__plugin_claudius_github__*`) for all API operations. Use wrapper scripts as CLI fallback when MCP is unavailable. All wrapper scripts are at `<plugin-root>/scripts/`.

## Get PR Context

**MCP (preferred)**:
- `pull_request_read` with `method: "get"` — title, body, URL, base/head branches, number
- `pull_request_read` with `method: "get_files"` — changed files with stats
- `pull_request_read` with `method: "get_diff"` — full diff

**Note**: `get_files` and `get_diff` may return large responses. See the parent skill's § Context Management for the subagent delegation pattern.

**CLI fallback**:
```bash
gh pr view --json number,title,body,url,baseRefName
gh pr view --json baseRefName -q .baseRefName
```

## PR-Level Comments

**MCP**: `add_issue_comment` to post; `pull_request_read` with `method: "get"` to read.

**CLI fallback**:
```bash
gh pr comment <number> --body "<markdown>"
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'
```

## Fetch Existing Reviews and Comments

Fetch before posting to avoid duplicates. Drop any finding already covered by an existing review (match by file:line and substance, not exact wording).

**MCP (preferred)**:
- `pull_request_read` with `method: "get_reviews"` — existing reviews
- `pull_request_read` with `method: "get_review_comments"` — inline comment threads with resolution status

**CLI fallback**:
```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh <owner/repo> <pr>
# -> {id, state, submitted_at, body, user}

${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
# -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}
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

## Post Draft Review

**MCP (preferred)**: `pull_request_review_write` — omit the `event` field to create a pending (draft) review.

**CLI fallback** (`gh-post-review.sh` strips `event` automatically — reviews always post as drafts):
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
  -> {id, state, submitted_at, body, user}

gh-post-review.sh <owner/repo> <pr> <json_file>
  -> Posts draft review. Input: {commit_id, body, comments: [{path, line, side, body}]}

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
