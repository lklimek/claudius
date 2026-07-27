# GitHub CLI Fallback

For fetching PR reviews and comments: see [pr-review.md](../../git-and-github/references/pr-review.md).

For general GitHub CLI operations: see [gh-cli-fallback.md](../../git-and-github/references/gh-cli-fallback.md).

## Posting a Reply

When `mcp__plugin_claudius_github__add_reply_to_pull_request_comment` (step 8) is unavailable:

```bash
${CLAUDE_SKILL_DIR}/../../scripts/gh-post-review-reply.sh <owner/repo> <pr> <comment_id> <body_file>
```

`comment_id` is the databaseId of the thread's first comment. The reply body is read from `body_file` (Markdown) — write it to a temp file first; there is no inline-argument form. Retries once via `ghsudo` on a 403. Outputs the new reply's html_url.
