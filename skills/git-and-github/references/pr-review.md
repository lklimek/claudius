# PR Review Operations

All operations use the `gh` CLI and the wrapper scripts at `<plugin-root>/scripts/`. `${CLAUDE_SKILL_DIR}` is not substituted in reference files: the caller writes the absolute `<plugin-root>` (the loading skill's `${CLAUDE_SKILL_DIR}/../..`) into each command.

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
<plugin-root>/scripts/gh-fetch-reviews.sh <owner/repo> <pr>
# -> [{id, state, submitted_at, body, user}]

<plugin-root>/scripts/gh-fetch-review-comments.sh <owner/repo> <pr>
# -> {id, path, line, original_line, body, user, in_reply_to_id, html_url}

<plugin-root>/scripts/gh-list-review-threads.sh <owner/repo> <pr>
# -> {id, isResolved, comments: [{databaseId, path, body}]}  (thread resolution status)
```

## Verify Lines Are Within the Diff

GitHub rejects inline comments on lines outside the diff (HTTP 422). Before posting:

1. Get the PR base SHA:
   ```bash
   <plugin-root>/scripts/gh-pr-base-sha.sh <owner/repo> <number>
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
python3 <plugin-root>/scripts/post_pr_review.py <owner/repo> <pr> <report.json> --body "<one-line verdict>" [--comments <comments.json>] [--min-severity MEDIUM] [--draft] [--dry-run]
```

- `--comments`: optional JSON `{"<final_id>": "comment text" | null}` written with the Write
  tool; omitted IDs get text built from the finding, `null` skips one.
- `metadata.commit` must match the current PR head; `--commit`, when supplied, must match
  both. The head is checked before and after fetching the diff and threads, and posting uses
  that SHA. A mismatch exits 2: re-run the review. Without `metadata.commit`, it warns and
  publishes COMMENT instead of APPROVE.
- Coverage requires an unresolved RIGHT-side thread on the same path with overlapping
  current lines and the exact title as a whole, case-insensitive phrase in its first comment.
  IDs alone never establish coverage. Incomplete thread pagination exits 1 without posting.
- Without `--draft` it publishes COMMENT, or APPROVE only with `metadata.commit`, when nothing
  is posted, no unresolved thread remains and no non-disputed finding is blocking or MEDIUM+.
  `--dry-run` prints the payload without posting. Input must be a schema-valid assembled
  `report.json`; otherwise exit 2.
- Outside code (fences per [GFM](https://github.github.com/gfm/#fenced-code-blocks); invalid
  fences count as text), @mentions and HTML comment openers are neutralized.
- Prints `{url, event, inline, in_body, omitted, covered_by_open_threads, skipped}`; `omitted`
  = findings that overflowed GitHub's size limit (named in the body, not posted).

## Post Draft Review (hand-built payload)

`gh-post-review.sh` strips `event` automatically — reviews always post as drafts. Write the
payload to `<SCRATCH_DIR>/pr-review.json` (any writable scratch dir) with the Write tool:

```json
{
  "commit_id": "<SHA>",
  "body": "See summary comment for full report.\n\n<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>",
  "comments": [
    {"path": "src/file.rs", "line": 42, "side": "RIGHT", "body": "Finding here."}
  ]
}
```

then post it:

```bash
<plugin-root>/scripts/gh-post-review.sh <owner/repo> <number> <SCRATCH_DIR>/pr-review.json
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
