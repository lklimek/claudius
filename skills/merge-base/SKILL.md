---
name: merge-base
description: "This skill should be used when the user asks to \"merge the base branch\", \"update this feature branch from base\", or resolve conflicts while merging base into a feature branch."
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(git branch --show-current), Bash(git status*), Bash(git rev-parse *), Bash(git fetch --all --prune), Bash(git symbolic-ref refs/remotes/origin/HEAD*), Bash(git merge-base *), Bash(git log *), Bash(git diff *), Bash(git merge *), Bash(git add *), Bash(git commit --no-edit), Bash(gh pr view *)
---

# Merge Base Branch

Merge the remote base branch into the current feature branch: pre-merge analysis, conflict resolution, behavioral change report. **Output**: summaries only — never dump raw diffs, file contents, or initial state unless asked.

## Phase 1: Sync with Remote

Fetch all remotes and merge the tracked branch (never rebase, never `git pull`: its `--upload-pack` runs arbitrary code); resolve any conflicts per Phase 4 before continuing.

```bash
CURRENT_BRANCH=$(git branch --show-current)
TRACKING=$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo "")

git fetch --all --prune

if [ -n "$TRACKING" ]; then
  git merge --no-edit "$TRACKING"
fi
```

## Phase 2: Identify the Base Branch

From PR metadata, using the `git-and-github` skill:

```bash
BASE_BRANCH=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null)
```

If no PR exists, fall back to the repo default branch:

```bash
BASE_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
```

If neither works, ask the user.

Merge from `origin/$BASE_BRANCH` (the remote-tracking ref, already updated by fetch) — not the local base branch, which may be stale.

## Phase 3: Pre-Merge Analysis

Read diffs and logs internally to build context (no diff/source output).

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

Also find **semantic overlaps** — no textual conflict but behavior changes (e.g., upstream changed a function signature or default value that local code relies on).

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

For each conflicted file:

1. **Read the conflict markers** — understand both sides using Phase 3 context
2. **Resolve intelligently** — preserve both sides' intent; when ambiguous, prefer preserving existing behavior
3. **Stage the resolution** — `git add <file>`
4. **Present to the user** — a table summarizing the conflict, not raw source:

| Area | Ours | Theirs | Resolution |
|---|---|---|---|
| `function_name()` | Added X | Changed Y | Combined: X + Y |

Ask for approval before continuing. After all conflicts are resolved and approved:

```bash
git commit --no-edit
```

If the user rejects a resolution, apply their feedback and re-present.

## Phase 5: Behavioral Change Report

The key deliverable: anything in the merge result that could change runtime behavior (read merged files internally). Assign an overall **Risk Factor (0-100%)** — likelihood of unintended behavioral change:
- **0-20%**: routine merge, disjoint changes, no behavioral overlap
- **21-50%**: minor touches — new defaults, added parameters (backward-compatible)
- **51-80%**: significant — modified control flow, changed defaults affecting existing callers, schema changes
- **81-100%**: breaking — incompatible signatures, algorithm swaps, data format changes

Look for: upstream signature changes affecting local callers; changed defaults (config, function, env fallbacks); control-flow changes in overlapping code; struct/API/schema changes on either side; lock files merged with incompatible versions; upstream imports shadowing local ones; tests that may now fail. For conflicted and flagged files, identify the upstream authors whose changes caused them — not every contributor.

### Report format

```
## Behavioral Change Report — Risk: <N>%

### Safe Changes
- <file> — <what changed, why it's safe>

### Changes Requiring Attention
- <file> — <what changed, potential impact>

### Relevant Upstream Contributors
| Author | Key Changes |
|---|---|
| @<github-handle> | <PR(s) that caused conflicts or semantic issues> |

### Recommended Follow-up
- [ ] <action items, if any>
```

Safe changes first, so the user confirms routine items quickly and focuses on what matters. If clean (risk ~0%), say so in one line and skip the sections.

## Error Recovery

On any mid-merge failure:

```bash
git merge --abort
```

Report what happened and let the user decide how to proceed.
