---
name: push
description: "This skill should be used when the user asks to \"commit and push\", \"create a PR\", \"ship this\", \"send changes upstream\", \"open a pull request\", or \"publish this branch\". It commits, pushes, creates a PR, and automatically creates a feature branch when currently on a base branch."
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
   - **If a policy exists, this PR MUST carry a version bump before it's done** — **exactly once per unmerged PR, not per commit**: a branch already carrying a bump gets its changelog entry amended, not a second bump; re-bump only if the SemVer category grows (patch → minor). "Not merged yet" never means the bump can be skipped. Same reasoning for compatibility: an unmerged PR's earlier commits don't constrain later ones (`coding-best-practices` § "Unmerged code isn't released").

3. **Stage and commit**
   - Review changes, check for secrets — warn and exclude if found
   - Stage and commit per `git-and-github` conventions

4. **Push** to remote

5. **PR**
   - PR body MUST follow the TL;DR → User story → Scenario → Detailed discussion skeleton per `git-and-github` §Creating a PR
   - If PR exists for this branch: update its title and description to reflect current changes
   - If no PR: create a draft PR with summary + test plan per `git-and-github`

## Notes

- Push per `git-and-github` § Safety Rules — coordinator-only, no confirmation needed for a feature-branch push
- After completing, do NOT push again without a new explicit `/push` or user request — one invocation = one push
