---
name: github
description: This skill MUST be used when using git or gh commands and interacting with GitHub, including but not limited to creating and updating PRs, filing issues, pushing code, managing branches, or interacting with GitHub in any way.
---

# GitHub Workflow

Guidelines for working with Git and GitHub CLI (`gh`).

**Core principle**: Prefer local `git` commands over `gh` whenever possible. Use `gh` only for GitHub-specific operations that have no local equivalent (PRs, issues, releases, API calls, Actions).

**Attribution**: Every PR, issue, and comment posted to GitHub **must** include the following footer (separated by a blank line from the body):

```
<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
```

## Git vs gh Decision Table

| Task | Use | Command |
|---|---|---|
| View diff | `git` | `git diff`, `git diff <base>...HEAD` |
| View log / history | `git` | `git log`, `git log --oneline` |
| View file at revision | `git` | `git show <ref>:<file>` |
| Branch operations | `git` | `git branch`, `git checkout`, `git switch` |
| Staging and committing | `git` | `git add <files>`, `git commit` |
| Stash changes | `git` | `git stash`, `git stash pop` |
| Fetch / pull / push | `git` | `git fetch`, `git pull`, `git push` |
| View changed files | `git` | `git diff --name-only`, `git diff --stat` |
| Get commit SHA | `git` | `git rev-parse HEAD` |
| Clone a repository | `gh` | `gh repo clone <owner>/<repo>` |
| Create a repository | `gh` | `gh repo create` |
| View PR metadata | `gh` | `gh pr view --json <fields>` |
| Create PR | `gh` | `gh pr create` |
| Merge PR | `gh` | `gh pr merge` |
| Comment on PR | `gh` | `gh pr comment` |
| Create / view issues | `gh` | `gh issue create`, `gh issue view` |
| List PRs / issues | `gh` | `gh pr list`, `gh issue list` |
| GitHub REST API | `gh` | `gh api <endpoint>` |
| View CI status | `gh` | `gh run list`, `gh run view` |
| Manage releases | `gh` | `gh release create`, `gh release list` |
| Manage labels | `gh` | `gh label create`, `gh label list` |
| Manage secrets | `gh` | `gh secret set` |
| Check PR diff on GitHub | `gh` | `gh pr diff <number>` |
| Edit PR (title/body/reviewers) | `gh` | `gh pr edit` |
| Review PR | `gh` | `gh pr review` |

## Git Commands

### Branching

```bash
# Create and switch to a new branch
git checkout -b <branch-name>

# List branches
git branch

# Delete a local branch (safe)
git branch -d <branch-name>
```

### Viewing Changes

```bash
# Unstaged changes
git diff

# Staged changes
git diff --cached

# All changes since branch diverged from base
git diff <base-branch>...HEAD

# Changed files only
git diff --name-only <base-branch>...HEAD
git diff --stat <base-branch>...HEAD

# View file at a specific revision
git show <branch>:<path/to/file>
```

### History

```bash
# Recent commits (short)
git log --oneline -20

# Commits since branch diverged
git log <base-branch>..HEAD --oneline

# Full diff of branch
git diff <base-branch>...HEAD
```

### Committing

Always stage specific files — avoid `git add .` or `git add -A` to prevent accidentally committing secrets or large files.

```bash
git add <file1> <file2>
git commit -m "$(cat <<'EOF'
<type>: <description>

<optional body>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

**Commit message format**: Use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary).

| Type | Use for |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Build, CI, tooling, dependencies |
| `perf` | Performance improvement |

Append `!` after the type for breaking changes (e.g. `feat!: remove legacy API`).

### Pushing

**Always ask the user for explicit confirmation before every push.** Never push automatically — even after committing, creating a PR, or any other workflow step.
Even is the user agreed to push earlier, ask again before next push.

```bash
# First push of a new branch (set upstream)
git push -u origin <branch-name>

# Subsequent pushes
git push
```

Never force-push to `main` or `master`. Force-push to feature branches only when explicitly requested.

## gh Commands

### Pull Requests

#### Creating a PR

Check if the repository has a PR template before creating:

```bash
# Check for PR template
git ls-tree HEAD --name-only -r .github/ | grep -i pull_request_template
```

If a template exists, read it and fill it in. Common template sections:
- **Issue being fixed or feature implemented** — problem statement, user story, and/or symptoms (error messages, logs, etc) of the issue being addressed.  Write WHY the PR exists, not necessarily what it does. Include issue number if applicable.
- **What was done?** — describe changes
- **How has this been tested?** — testing details
- **Breaking changes** — describe and add `!` to title
- **Checklist** — self-review, tests, docs

When applicable (eg. new features), include a user story in the PR description. User story should be informal, 1 or 2 paragraph description of what the user can achieve with the PR. It shouldn't give any technical details, it shouldn't describe the implementation. It should only show what the user will be able to achieve. You can start with a statement like "Imagine you are <user> and you want to <goal>".

```bash
gh pr create --draft --title "<type>: <description>" --body "$(cat <<'EOF'
## Issue being fixed or feature implemented

### User Story

### Details

Closes #<issue-number>

## What was done?

<description of changes>

## How has this been tested?

<testing details>

## Breaking Changes

None

## Checklist

- [x] I have performed a self-review of my own code
- [x] I have added or updated relevant tests
- [x] I have made corresponding changes to the documentation if needed

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
EOF
)"
```

If no template exists, use a concise format:

```bash
gh pr create --draft --title "<type>: <description>" --body "$(cat <<'EOF'
## Summary

### User Story
Imagine you are <user> and you want to <goal>...

### Details
<1-3 bullet points>


## Test plan
- [ ] <test step>

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
EOF
)"
```

#### Viewing a PR

```bash
# PR metadata
gh pr view <number> --json number,title,body,url,baseRefName,headRefName

# PR diff (when you need GitHub's view, not local)
gh pr diff <number>

# List open PRs
gh pr list
```

#### Commenting on a PR

```bash
gh pr comment <number> --body "$(cat <<'EOF'
<comment text>

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
EOF
)"
```

#### Editing a PR

```bash
# Update title and body
gh pr edit <number> --title "<new title>" --body "$(cat <<'EOF'
<PR body content>
EOF
)"

# Or read body from file
SESSION_DIR=$(mkdir -p /tmp/claude && mktemp -d /tmp/claude/XXXXXX)
# ... write body to $SESSION_DIR/pr-body.md ...
gh pr edit <number> --body-file "$SESSION_DIR/pr-body.md"

# Add/remove reviewers, labels, assignees, projects, milestone
gh pr edit <number> --add-reviewer <login1>,<login2>
gh pr edit <number> --add-label "bug,help wanted" --remove-label "core"
gh pr edit <number> --add-assignee "@me"
```

#### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft reviews.** The user must publish the review themselves on GitHub.

For inline file comments, create a draft review (omit the `"event"` field). The `gh-post-review.sh` wrapper enforces draft mode by stripping any `event` field from the input JSON:

```bash
cat > "$SESSION_DIR/pr-review.json" << 'ENDJSON'
{
  "commit_id": "<SHA>",
  "body": "Review summary.\n\n<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>",
  "comments": [
    {"path": "src/file.rs", "line": 42, "side": "RIGHT", "body": "Finding here."}
  ]
}
ENDJSON
../../scripts/gh-post-review.sh <owner> <repo> <number> "$SESSION_DIR/pr-review.json"
```

#### PR Review Comments

**Always use wrapper scripts — never call `gh api` directly for PR review operations.** Scripts handle pagination, `--jq` filtering, and input validation. Invoked via `../../scripts/`.

```
../../scripts/gh-fetch-review-comments.sh <owner> <repo> <pr_number>
  → JSON per line: {id, path, line, original_line, body, user, in_reply_to_id, html_url}

../../scripts/gh-fetch-reviews.sh <owner> <repo> <pr_number>
  → JSON per line: {id, state, submitted_at, body, user}

../../scripts/gh-post-review.sh <owner> <repo> <pr_number> <json_file>
  → Posts draft review. Input JSON: {commit_id, body, comments: [{path, line, side, body}]}
  → Strips "event" field to enforce draft mode. Returns review html_url.

../../scripts/gh-request-reviewer.sh <owner> <repo> <pr_number> <reviewer>
  → Adds reviewer to PR.

../../scripts/gh-list-review-threads.sh <owner> <repo> <pr_number>
  → GraphQL JSON: {id, isResolved, comments: [{databaseId, path, body}]}

../../scripts/gh-resolve-review-thread.sh <thread_id>
  → Resolves thread by GraphQL node ID (from gh-list-review-threads.sh).
  → Ask user before resolving. Never resolve partially addressed threads.

../../scripts/gh-pr-base-sha.sh <owner> <repo> <pr_number>
  → Single line: base commit SHA.

../../scripts/diff-anchors.py <file_path> [<file_path> ...]
  → "path → sha256". For diff URLs: ...files#diff-<SHA256>R<line>
```

For PR-level (non-diff) comments: `gh pr view <number> --json comments --jq '.comments[] | {author: .author.login, body, url}'`

### Issues

```bash
# Check for issue templates
git ls-tree HEAD --name-only -r .github/ | grep -i issue_template

# List issues
gh issue list
gh issue list --label bug

# View issue
gh issue view <number>

# Create issue (fill template if exists; always append attribution footer)
gh issue create --title "<title>" --body "<body>

<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>"
```

### GitHub API

**Never call `gh api` directly for PR review/comment operations.** Always use the wrapper scripts from `scripts/` — they handle pagination, `jq` filtering (via `--jq`, avoiding shell escaping issues), and input validation. See the `PR Review Comments` section above for the full list of scripts.

For other `gh api` operations not covered by wrapper scripts or high-level `gh` subcommands, prefer `--jq` over piping to `jq` to avoid shell escaping problems:

```bash
# Prefer --jq (processed by gh, not bash)
gh api /advisories?ecosystem=<eco>&affects=<pkg> --jq '.[] | {id, summary}'

# Avoid: piping to jq risks shell interpretation issues (e.g. != becomes \!= )
# gh api ... | jq '.[] | select(.body != "")'  # BAD — ! triggers history expansion
```

### Repositories

```bash
# Clone
gh repo clone <owner>/<repo>
gh repo clone <owner>/<repo> <local-path>

# Create
gh repo create <name> --private
gh repo create <org>/<name> --public

# Set default remote
gh repo set-default <owner>/<repo>
```

### CI / Actions

```bash
# List recent workflow runs
gh run list

# View a specific run
gh run view <run-id>

# Watch a running workflow
gh run watch <run-id>
```

### Releases

```bash
# Create a release
gh release create <tag> --title "<title>" --notes "<notes>"

# List releases
gh release list
```

## Safety Rules

1. **Always ask before publishing anything to GitHub** — this includes commits, pushes, PRs, issues, comments, reviews, etc. Always ask for confirmation and details before performing any action that changes state of GitHub.
2. **Never force-push to main/master** — warn the user if they request it
3. **Never use `git add .` or `git add -A`** — stage specific files to avoid leaking secrets
4. **Never use interactive flags** (`-i`) — they require terminal input
5. **Never skip hooks** (`--no-verify`) unless explicitly requested
6. **Never amend after hook failure** — create a new commit instead
7. **Never amend commits** — always create new commits. Do not use `--amend` even if asked
8. **Check for `.env`, credentials, or secret files** before staging — warn if found
9. **Check for PR/issue templates** before creating PRs or issues — use them if they exist

## Escaping and Formatting

- Use HEREDOCs (`<<'EOF'`) for multi-line bodies to avoid shell escaping issues
- Use `--jq` with `gh api` to extract specific fields
- Use `--json <fields>` with `gh pr view` / `gh issue view` to get structured data
- When posting JSON payloads via `gh api`, write to a temp file and use `--input`, especially for arrays
- **Prefer `--jq` over `| jq`** when using `gh api` — `--jq` is processed by `gh` internally, bypassing bash interpretation. Piping to `jq` exposes filters to shell expansion (e.g., `!=` breaks because `!` triggers history expansion)

## Troubleshooting

* If any `gh` command fails with a "Projects (classic)" GraphQL error, check if `gh version` is up to date. If not, `gh` upgrade is needed.
