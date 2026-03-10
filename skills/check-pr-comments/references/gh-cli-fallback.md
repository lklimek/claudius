# GitHub CLI Fallback

Use this reference when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable.

## Fetching PR Comments

Use wrapper scripts (located at `../../scripts/` relative to this skill's base dir):

```bash
# Inline review comments
../../scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
  -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

# Review summaries
../../scripts/gh-fetch-reviews.sh <owner/repo> <pr>
  -> {id, state, submitted_at, body, user}

# PR-level (non-diff) comments
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'

# Review threads with resolution status
../../scripts/gh-list-review-threads.sh <owner/repo> <pr>
  -> {id, isResolved, comments: [{databaseId, path, body}]}
```

## Resolving Review Threads

```bash
../../scripts/gh-resolve-review-threads.sh <thread_id> [thread_id ...]
```

Resolves all given threads in a single GraphQL API call. Always ask the user before resolving.
