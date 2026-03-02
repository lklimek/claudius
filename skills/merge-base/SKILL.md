---
name: merge-base
description: >
  Careful merge of the remote base branch into the current feature branch. Use when the user wants
  to sync their branch with main/master, merge upstream changes, update from base, or rebase-via-merge.
  Also use when the user says "merge base", "pull from main", "sync with main", "update branch",
  or any variation of incorporating base branch changes into the current working branch.
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(git branch *), Bash(git rev-parse *), Bash(git fetch *), Bash(git pull *), Bash(git symbolic-ref refs/remotes/origin/HEAD), Bash(git merge-base *), Bash(git merge *), Bash(git merge --abort), Bash(git log *), Bash(git diff *), Bash(git add *), Bash(git commit *), Bash(git status), Bash(git status *), Bash(gh pr view *)
---

# Merge Base Branch

Merge the remote base branch into the current feature branch with pre-merge analysis, intelligent
conflict resolution, and a behavioral change report.

**Output philosophy**: Be concise. Show summaries, not diffs or source code. The user will ask
for details if they want them. Never dump raw diffs, full file contents, or initial state unless
explicitly requested.

## Phase 1: Sync with Remote

Fetch all remotes and pull tracked branch changes (merge mode, never rebase).

```bash
CURRENT_BRANCH=$(git branch --show-current)
TRACKING=$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo "")

git fetch --all --prune

if [ -n "$TRACKING" ]; then
  git pull --no-rebase
fi
```

If the pull produces conflicts, resolve them (see Phase 4) before continuing.

## Phase 2: Identify the Base Branch

Determine the base branch from PR metadata using the `github` skill:

```bash
BASE_BRANCH=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null)
```

If no PR exists, fall back to the repo default branch:

```bash
BASE_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
```

If neither works, ask the user.

Use `origin/$BASE_BRANCH` (the remote-tracking ref, already updated by fetch) for the merge — not
the local base branch, which may be stale.

## Phase 3: Pre-Merge Analysis

Understand both sides of the merge internally. Read the diffs and logs to build context for
conflict resolution and behavioral analysis. Do NOT output diffs or source — only summaries.

```bash
MERGE_BASE=$(git merge-base origin/$BASE_BRANCH HEAD)

# Our changes
git log --oneline $MERGE_BASE..HEAD
git diff --stat $MERGE_BASE..HEAD
git diff $MERGE_BASE..HEAD

# Their changes
git log --oneline $MERGE_BASE..origin/$BASE_BRANCH
git diff --stat $MERGE_BASE..origin/$BASE_BRANCH
git diff $MERGE_BASE..origin/$BASE_BRANCH
```

### Overlap and semantic analysis

Identify files modified on **both** sides:

```bash
comm -12 \
  <(git diff --name-only $MERGE_BASE..HEAD | sort) \
  <(git diff --name-only $MERGE_BASE..origin/$BASE_BRANCH | sort)
```

Also look for **semantic overlaps** — cases where there's no textual conflict but behavior
changes (e.g., upstream changed a function signature or default value that local code relies on).

Report a brief summary to the user:
- What each side changed (1-2 sentences per side)
- Overlapping files (if any)
- Semantic overlaps identified (if any)

## Phase 4: Execute the Merge

```bash
git merge origin/$BASE_BRANCH --no-edit
```

### If no conflicts

The merge commits automatically. Proceed to Phase 5.

### If conflicts occur

Git will list conflicted files. For each one:

1. **Read the conflict markers** — understand both sides using Phase 3 context
2. **Resolve intelligently** — preserve intent from both sides. When ambiguous, prefer the
   version that preserves existing behavior.
3. **Stage the resolution** — `git add <file>`
4. **Present to the user** — use a table summarizing the conflict, not raw source:

| Area | Ours | Theirs | Resolution |
|---|---|---|---|
| `function_name()` | Added X | Changed Y | Combined: X + Y |

Ask for approval before continuing.

After all conflicts are resolved and the user approves:

```bash
git commit --no-edit
```

If the user rejects a resolution, apply their feedback and re-present.

## Phase 5: Behavioral Change Report

This is the most important deliverable. Analyze the merge result for anything that could change
runtime behavior. Read the merged files internally — do not dump diffs to the user.

Assign an overall **Risk Factor (0-100%)** reflecting the likelihood that the merge introduced
unintended behavioral changes:
- **0-20%**: Routine merge, disjoint changes, no behavioral overlap
- **21-50%**: Minor behavioral touches — new defaults, added parameters (backward-compatible)
- **51-80%**: Significant behavioral changes — modified control flow, changed defaults affecting
  existing callers, schema changes
- **81-100%**: Breaking changes — incompatible signatures, algorithm swaps, data format changes

### What to look for

- **Function signature changes** — parameters added/removed/reordered upstream affecting local callers
- **Default value changes** — config defaults, function defaults, env var fallbacks changed upstream
- **Control flow changes** — conditionals, early returns, error handling paths in overlapping code
- **Type/schema changes** — struct fields, API shapes, database schemas changed on either side
- **Dependency version conflicts** — lock files merged with potentially incompatible versions
- **Import/module resolution** — new upstream imports that shadow or conflict with local ones
- **Test expectations** — tests that may now fail due to changed behavior from either side

### Report format

```
## Behavioral Change Report — Risk: <N>%

### Safe Changes
- <file> — <what changed, why it's safe>

### Changes Requiring Attention
- <file> — <what changed, potential impact>

### Recommended Follow-up
- [ ] <action items, if any>
```

Show safe changes first so the user can quickly confirm the routine stuff and focus attention on
what matters. If the report is clean (risk ~0%), say so in one line and skip the sections.

## Error Recovery

If anything goes wrong mid-merge:

```bash
git merge --abort
```

Then report what happened and let the user decide how to proceed.
