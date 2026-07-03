# GitHub CLI Fallback

Use this reference when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable.

## Fetching PR Comments

Use wrapper scripts (located at `${CLAUDE_SKILL_DIR}/../../scripts/`):

```bash
# Inline review comments
${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
  -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

# Review summaries
${CLAUDE_SKILL_DIR}/../../scripts/gh-fetch-reviews.sh <owner/repo> <pr>
  -> {id, state, submitted_at, body, user}

# PR-level (non-diff) comments
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'

# Review threads with resolution status
${CLAUDE_SKILL_DIR}/../../scripts/gh-list-review-threads.sh <owner/repo> <pr>
  -> {id, isResolved, comments: [{databaseId, path, body}]}
```

## Resolving Review Threads

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <thread_id> [thread_id ...]
# OR (REST/numeric IDs need PR context for conversion):
${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh <owner/repo> <pr_number> --id <id> [--id <id> ...]
```

Resolves all given threads in a single GraphQL API call. The `--id` form accepts `PRRT_*`, `discussion_r<n>`, and bare numeric `databaseId` (auto-converted via PR context). Always ask the user before resolving.

## Posting a Reply

When `mcp__plugin_claudius_github__add_reply_to_pull_request_comment` (step 8) is unavailable, post an inline review-thread reply via the wrapper:

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-post-review-reply.sh <owner/repo> <pr> <comment_id> <body_file>
```

`comment_id` is the databaseId of the thread's first comment. The reply body is read from `body_file` (Markdown) — write the reply to a temp file first, since the body comes from a file, not an inline argument. Retries once via `ghsudo` on a 403. Outputs the new reply's html_url.
