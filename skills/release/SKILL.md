---
name: release
description: Bump version (SemVer 2.0), update changelog, commit, push, and create GitHub release. Auto-detects project tech stack (Rust, Python, JS/TS, Claude Code plugins, etc.). Args: major|minor|patch or auto-detect from commits. User-invocable only — agents must not invoke this skill autonomously.
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

Stage all modified version files, lock files, and `CHANGELOG.md`. Commit as `chore: release v{new}`.

Push to the current branch. If on a base branch (main, master, etc.), create a release branch first (`release/v{new}`). In all cases, create a PR targeting the base branch using `gh pr create`.

### 7. Monitor CI

Use `gh run list` to find workflow runs for the PR branch, then `gh run watch {run_id} --exit-status` to wait. Do NOT poll in a loop — `gh run watch` streams and exits on completion.

1. Watch all PR CI runs until they complete.
2. **If CI fails** → read logs with `gh run view {run_id} --log-failed`, report the failure to the user with full context, and **stop immediately**. Do NOT attempt fixes — the release process must not silently retry.
3. **If CI passes** → squash-merge the release PR automatically using `gh pr merge --squash`. Then proceed to Step 8.

### 8. Create GitHub Release

Write the new changelog entry (this version only) to a temp file:
```bash
gh release create v{new} --title "v{new}" --notes-file {changelog_temp_file}
```

Do NOT ask for confirmation — the user already approved the version in Step 3.

### 9. Monitor Release Workflows

The GitHub release triggers downstream workflows (binary builds, package publishing, Docker image builds, etc.). Monitor these **in the background** so the user can continue working — do not block on them.

1. Wait a few seconds for workflows to queue, then list runs triggered by the release tag:
   ```bash
   gh run list --limit 10
   ```
   Identify runs triggered by the `v{new}` tag or release event.

2. Watch all runs in parallel in the background:
   ```bash
   gh run watch {run_id} --exit-status  # run_in_background: true for each
   ```

3. **If any release workflow fails** → this is critical. Immediately:
   - Read failed logs: `gh run view {run_id} --log-failed`
   - Report the failure to the user with full context (workflow name, job, error)
   - Do NOT attempt automated fixes on release workflows — escalate immediately
   - Release build failures may leave partial artifacts; warn the user

4. **If all release workflows succeed** → proceed to Step 10.

### 10. Summary

Print: version change, updated files, release URL, release workflow results (pass/fail per workflow), and any warnings.

## Constraints

- NEVER create the release before pushing — tag must reference a remote commit.
- NEVER skip lock file sync.
- If any step fails, stop and report. Do not continue with partial state.
- If versions are inconsistent and user hasn't confirmed scope, do not proceed.
- NEVER push directly to a base branch (main, master, etc.) — always use a release branch and PR.
- Do NOT ask for confirmation before creating the GitHub release — user approved at version selection.
- Always squash-merge release PRs (`gh pr merge --squash`) — never use merge commits or rebase.
- Release workflow failures are CRITICAL — escalate immediately, do not attempt automated fixes.
- Use `gh run watch` for CI monitoring — never poll `gh run list` or `gh run view` in a loop.
