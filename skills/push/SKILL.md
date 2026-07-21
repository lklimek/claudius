---
name: push
description: "Commit, push, and create PR. Auto-creates feature branch if on base. Use when user wants to commit and push, create a PR, ship work, send changes upstream, open a pull request, or publish a branch."
user-invocable: true
allowed-tools: ["Bash", "Read", "Grep", "Glob"]
---

# Push

## Prerequisites

Load `claudius:git-and-github` skill first — all commit, push, PR, and attribution conventions come from there.

## Steps

1. **Ensure feature branch**
   - Base branch: read from `gitStatus` context (`Main branch: ...`). Fallback: `git remote show origin`
   - If ON the base branch: fetch, create a feature branch (`feat/...`, `fix/...`, `chore/...` from context), switch to it

2. **Version bump** (if applicable)
   - Check project's `CLAUDE.md` for versioning policy (SemVer, changelog, version file locations)
   - **If policy exists, this PR MUST carry a version bump before it's considered done** — bump version and update changelog before committing (or before marking the PR ready, if bumping later once full scope is known).
   - **Exactly once per unmerged PR, not per commit**: if this branch already carries a version bump from an earlier commit and hasn't merged yet, don't bump again — amend the existing changelog entry instead. Re-bump only if the change's SemVer category grows (e.g. patch → minor). Never conclude "not merged yet" or "already bumped once elsewhere" means the bump can be skipped for this PR itself.
   - Same reasoning covers backward compatibility: nothing in an unmerged PR is released yet, so its own earlier commits don't constrain later ones on the same branch.

3. **Stage and commit**
   - Review changes, check for secrets — warn and exclude if found
   - Stage and commit per `git-and-github` conventions

4. **Push** to remote

5. **PR**
   - PR body MUST follow the TL;DR → User story → Scenario → Detailed discussion skeleton per `git-and-github` §Creating a PR
   - If PR exists for this branch: update its title and description to reflect current changes
   - If no PR: create a draft PR with summary + test plan per `git-and-github`

## Notes

- **No push confirmation needed** — user explicitly invoked `/push`, intent is clear
- This overrides the "ask before push" rule from `git-and-github` **for this invocation only**
- After completing, do NOT push again without a new explicit `/push` or user request — one invocation = one push
