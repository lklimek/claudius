---
name: release
description: "This skill should be used when the user asks to \"bump the version\", \"cut a release\", or \"create a GitHub release\". It applies SemVer 2.0, updates the changelog, commits, pushes, creates the release, and auto-detects Rust, Python, JS/TS, Claude Code plugin, and other supported stacks. Arguments are major, minor, patch, or auto-detection from commits. User-invocable only — agents must not invoke it autonomously."
user-invocable: true
disable-model-invocation: true
---

# Release

Load `claudius:git-and-github` first — all commit, push, and PR conventions come from there.

## Arguments

Optional: `major`, `minor`, or `patch`. If omitted, auto-detect from git history.

## Steps

### 0. Pre-flight

1. Working tree must be clean. If dirty, stop and ask.
2. If on a feature branch, warn and ask whether to release from here or switch to main first.

### 1. Detect Project Stack

Scan repo for version-carrying files:

| File | Version location |
|---|---|
| `Cargo.toml` (root/workspace) | `[package].version` or `[workspace.package].version` |
| `Cargo.toml` (workspace members) | each member's `[package].version` (may use `workspace = true`) |
| `pyproject.toml` | `[project].version` or `[tool.poetry].version` |
| `setup.py` / `setup.cfg` | `version=` kwarg or `[metadata].version` |
| `package.json` (root + workspaces) | `"version"` field |
| `lerna.json` | `"version"` (`"independent"` = per-package) |
| `.claude-plugin/plugin.json` | `"version"` field |
| `version.txt` / `VERSION` | entire file content |

If no version files found, stop and ask.

### 2. Validate Version Consistency

Collect all detected versions:

1. **All identical** — proceed.
2. **Intentionally independent** (Cargo workspace members with explicit versions, lerna `"independent"`, npm workspaces with different versions) — list each component + version, ask user which to release.
3. **Unexpectedly inconsistent** — stop, show mismatch table, let user decide.

### 3. Determine New Version

1. Get commits since last tag:
   ```bash
   git log $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --oneline --no-decorate
   ```

2. **Investigate actual diffs** — commit prefixes can be misleading. Read full diffs for commits touching public APIs, interfaces, or config formats.

3. If bump type provided as argument, use it. Otherwise auto-detect:
   - **major**: breaking changes in diffs, `BREAKING CHANGE` in body, or type suffix `!`
   - **minor**: new features in diffs, or `feat:` commits
   - **patch**: only fixes, refactors, docs, CI
   - Default to `patch` if unclear

4. **Ask for confirmation.** Show: current → proposed version, commit list, key diff findings, justification, files to update, post-bump commands. Options: proposed (recommended), alternatives, or abort.

### 4. Update Version Files

Update all version files (within confirmed scope from Step 2). Then sync lock files:
- `Cargo.lock` → `cargo update --workspace`
- `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` → run matching package manager install
- `poetry.lock` → `poetry lock`

### 5. Generate Changelog Entry

If `CHANGELOG.md` exists, prepend new entry after header. If absent, create it. Format per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Map conventional commit types to sections. Omit empty sections. If compare links exist at bottom, add one for this version.

### 6. Commit and Push

Stage all modified version files, lock files, and `CHANGELOG.md`. Commit as `chore: release v{new}`. Push per `git-and-github` conventions. Verify push succeeds before proceeding.

### 7. Create GitHub Release

Write new changelog entry (this version only) to a temp file:
```bash
gh release create v{new} --title "v{new}" --notes-file {changelog_temp_file}
```

### 8. Summary

Print: version change, updated files, release URL, triggered workflows (if known from CI config).

## Constraints

- NEVER create the release before pushing — tag must reference a remote commit.
- NEVER skip lock file sync.
- If any step fails, stop and report. Do not continue with partial state.
- If versions are inconsistent and user hasn't confirmed scope, do not proceed.
