---
name: merge-base
description: "This skill should be used when the user asks to \"merge the base branch\", \"update this feature branch from base\", or resolve conflicts while merging base into a feature branch. It merges (never rebases) the remote base, gates conflict resolutions on user approval, and reports behavioral risk."
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(git branch --show-current), Bash(git status*), Bash(git rev-parse *), Bash(git fetch --all --prune), Bash(git symbolic-ref refs/remotes/origin/HEAD*), Bash(git merge-base *), Bash(git log *), Bash(git diff *), Bash(git merge *), Bash(git add *), Bash(git commit --no-edit), Bash(gh pr view *)
---

# Merge Base Branch

Merge the remote base branch into the current feature branch: pre-merge analysis, conflict resolution, behavioral change report. **Output**: summaries only — never dump raw diffs, file contents, or initial state unless asked.

## 1. Sync

`git fetch --all --prune`, then merge the branch's own upstream if it has one (`git merge --no-edit @{upstream}`). **Never rebase; never `git pull`** (its `--upload-pack` runs arbitrary code). Conflicts here are resolved per step 4.

## 2. Base Branch

From PR metadata (prints the bare branch name `<base>`); fall back to the repo default branch (prints `origin/<base>` already — do not prefix it again); if neither resolves, ask the user:

```bash
gh pr view --json baseRefName -q .baseRefName
git symbolic-ref refs/remotes/origin/HEAD --short
```

Merge from `origin/<base>` (the remote-tracking ref the fetch just updated) — never the local base branch, which may be stale.

## 3. Pre-Merge Analysis

Read both sides' logs and diffs since `git merge-base origin/<base> HEAD` internally. Find files modified on both sides AND **semantic overlaps** — no textual conflict, but upstream changed something local code relies on (a signature, a default, a schema). Tell the user in a few lines: what each side changed, overlapping files, semantic overlaps.

## 4. Merge

```bash
git merge origin/<base> --no-edit
```

On conflicts, per file: resolve preserving both sides' intent (when ambiguous, preserve existing behavior), `git add <file>`, and present a summary table — not raw source:

| Area | Ours | Theirs | Resolution |
|---|---|---|---|
| `function_name()` | Added X | Changed Y | Combined: X + Y |

**Ask for approval before committing.** On rejection, apply the feedback and re-present. Once every resolution is approved: `git commit --no-edit`.

## 5. Behavioral Change Report

The key deliverable: anything in the merge result that could change runtime behavior — upstream signature changes affecting local callers, changed defaults (config, function, env fallbacks), control-flow changes in overlapping code, schema/API changes, lock files merged to incompatible versions, upstream imports shadowing local ones, tests that may now fail. Assign an overall **Risk Factor (0–100%)**, the likelihood of unintended behavioral change:

- **0–20%**: routine, disjoint changes
- **21–50%**: minor touches — new defaults, backward-compatible parameters
- **51–80%**: significant — modified control flow, changed defaults affecting existing callers, schema changes
- **81–100%**: breaking — incompatible signatures, algorithm swaps, data format changes

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

Safe changes first. Contributors: only the upstream authors whose changes caused conflicts or flagged items. If clean (risk ~0%), say so in one line and skip the sections.

## Error Recovery

On any mid-merge failure: `git merge --abort`, report what happened, and let the user decide.
