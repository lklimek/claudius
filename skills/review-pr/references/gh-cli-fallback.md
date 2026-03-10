# GitHub CLI Fallback

Use this reference when the GitHub MCP server (`mcp__plugin_claudius_github__*`) is unavailable.

## PR Context

```bash
# PR metadata
gh pr view --json number,title,body,url,baseRefName

# Base branch name
gh pr view --json baseRefName -q .baseRefName
```

## Fetching Reviews and Comments

```bash
# Existing reviews
../../scripts/gh-fetch-reviews.sh <owner/repo> <pr>
  -> {id, state, submitted_at, body, user}

# Inline review comments
../../scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
  -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}
```

## Posting (always CLI -- no MCP equivalent for batch review posting)

```bash
# Summary comment
gh pr comment <number> --body "<markdown>"

# Draft review with inline comments
../../scripts/gh-post-review.sh <owner/repo> <number> <json_file>
  -> Posts draft review. Input: {commit_id, body, comments: [{path, line, side, body}]}

# PR base SHA (for verifying lines are within diff)
../../scripts/gh-pr-base-sha.sh <owner/repo> <number>
  -> Base commit SHA
```
