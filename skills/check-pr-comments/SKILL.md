---
name: check-pr-comments
description: Verify whether existing PR review comments have been addressed in code. Checks out the branch, verifies each comment against current code, resolves addressed threads, and produces a structured report. Use when asked to check, triage, or verify PR review feedback.
allowed-tools: Read, Grep, Glob, Bash(gh pr view *), Bash(gh pr checkout *), Bash(gh api *), Bash(git pull *), Bash(git fetch *), Bash(*diff-anchors.py *)
---

# Check PR Comments Workflow

When asked to check/triage/verify existing PR review comments, follow this workflow.

## 1. Fetch All Comments

Use `gh pr view --json` where possible; fall back to `gh api` for inline review comments (not exposed by the CLI).

```bash
# Inline review comments (primary focus) -- requires gh api, no CLI equivalent
gh api repos/<owner>/<repo>/pulls/<number>/comments --paginate \
  --jq '.[] | {id, path, line, original_line, body, user: .user.login, in_reply_to_id, html_url}'

# PR-level (issue) comments -- CLI available
gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'

# Review summaries -- CLI available
gh pr view <number> --json reviews --jq '.reviews[] | {author: .author.login, state, body}'
```

## 2. Checkout and Pull the PR Branch

```bash
gh pr checkout <number>
git pull
```

## 3. Verify Each Comment Against Current Code

For every inline comment, read the file at the referenced location and **verify whether the identified issue is actually fixed** -- not just whether the code changed. Specifically:

- Read the current code at the location the comment references
- Understand what the comment is asking for
- Determine if the current code satisfies the request (semantically, not just syntactically)
- For comments with multiple sub-items, verify each one independently
- A comment is only "resolved" if **all** of its sub-items are addressed

## 4. Produce a Structured Report

The report has three sections: **Resolved Comments**, **Unresolved Comments**, and **Summary**.

Items are numbered globally across both sections (e.g. if resolved has 1-6, unresolved starts at 7).

### Building diff-view links

Compute SHA256 of each file path to construct links into the PR diff view using the bundled helper script:

```bash
scripts/diff-anchors.py path/to/file1.rs path/to/file2.rs
```

Link format:
- Single line: `https://github.com/<owner>/<repo>/pull/<number>/files#diff-<SHA256>R<line>`
- Line range: `https://github.com/<owner>/<repo>/pull/<number>/files#diff-<SHA256>R<start>-R<end>`

### Resolved Comments and Unresolved Comments sections

Both sections use identical item format. The only differences are:
- Unresolved items include a severity tag `[<SEVERITY>]` in the title
- The verdict word differs

Severity levels (UPPERCASE): CRITICAL > HIGH > MEDIUM > LOW > INFO.
Verdict values (UPPERCASE): RESOLVED, UNRESOLVED.

Item format:

```markdown
#### <N>. <Reviewer> #<commentId> -- [<SEVERITY>] <title>

**Review:** [<Reviewer>](https://github.com/<owner>/<repo>/pull/<number>/files#r<commentId>)
**Location:** [`<file>:<lines>`](https://github.com/<owner>/<repo>/pull/<number>/files#diff-<SHA256>R<start>-R<end>)

<Multi-line description of what the comment asked for.>

**Verdict:** RESOLVED / UNRESOLVED

<Multi-line explanation: how the code addresses the issue, or what remains unaddressed and why.>
```

For resolved items, the `[<SEVERITY>]` tag is omitted from the title.

### Summary section

Table covering all comments from both sections, using the same global `<N>`:

```markdown
| # | Location | Verdict | Comments |
|---|----------|---------|----------|
| <N> | `<file>:<lines>` | RESOLVED / UNRESOLVED | <Short explanation> |
```

- **#**: the same global number `<N>` used in the detailed sections above
- **Location**: file name and line numbers only (no link)
- **Verdict**: one word, UPPERCASE -- RESOLVED or UNRESOLVED
- **Comments**: optional short explanation of the verdict

## 5. Resolve Addressed Threads

**Always ask the user for confirmation before resolving any threads.**

After the report is presented and the user approves, resolve addressed review threads via GraphQL:

```bash
# Get thread IDs (map comment databaseId to GraphQL thread id)
gh api graphql -f query='{
  repository(owner: "<owner>", name: "<repo>") {
    pullRequest(number: <number>) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          comments(first: 1) {
            nodes { databaseId path body }
          }
        }
      }
    }
  }
}'

# Resolve a single thread
gh api graphql -f query='mutation {
  resolveReviewThread(input: {threadId: "<THREAD_ID>"}) {
    thread { isResolved }
  }
}'
```

Only resolve threads where verification confirms the issue is fixed. Never resolve threads that are only partially addressed.
