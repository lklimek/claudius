---
name: release
description: Bump version (SemVer 2.0), update changelog, commit, push, and create GitHub release. Auto-detects project tech stack (Rust, Python, JS/TS, Claude Code plugins, etc.). Args: major|minor|patch or auto-detect from commits. User-invocable only — agents must not invoke this skill autonomously.
user-invocable: true
disable-model-invocation: true
---

# Release

Bump version, commit, push, and create a GitHub release. Works with any tech stack.

## Arguments

Optional: `major`, `minor`, or `patch`. If omitted, auto-detect from git history.

## Steps

### 0. Pre-flight

1. Verify working tree is clean (`git status --porcelain`). If dirty, stop and ask.
2. If on a feature branch (not main/master), warn and ask whether to release from here or switch first.

### 1. Detect Project Stack

Scan the repo root for version-carrying files. Check ALL of the following that exist:

| File | Tech | Version location |
|---|---|---|
| `Cargo.toml` (root or workspace) | Rust | `[package].version` or `[workspace.package].version` |
| `Cargo.toml` (workspace members) | Rust | each member's `[package].version` (may use `workspace = true`) |
| `pyproject.toml` | Python | `[project].version` or `[tool.poetry].version` |
| `setup.py` / `setup.cfg` | Python (legacy) | `version=` kwarg or `[metadata].version` |
| `package.json` (root) | JS/TS | `"version"` field |
| `package.json` (workspaces) | JS/TS monorepo | each workspace's `"version"` (may be independently versioned) |
| `lerna.json` | JS/TS monorepo | `"version"` (`"independent"` = per-package versioning) |
| `.claude-plugin/plugin.json` | Claude Code plugin | `"version"` field |
| `version.txt` / `VERSION` | Generic | entire file content |

Also note lock files that need syncing:
- `Cargo.lock` — run `cargo update --workspace` after bumping `Cargo.toml`
- `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` — run the matching package manager's install/update

**If no version files found**, stop and ask the user where the version lives.

### 2. Validate Version Consistency

Collect all detected versions. Three outcomes:

1. **All identical** — proceed with that version as `{old}`.
2. **Intentionally independent** — some ecosystems use independent versioning (Cargo workspace members with explicit versions, lerna `"independent"`, npm workspaces with different versions). If detected:
   - List each component and its version
   - Ask user: "These appear independently versioned. Which component(s) should I release?" or "Should I bump all to the same version?"
   - Proceed only with confirmed scope
3. **Unexpectedly inconsistent** — e.g., `plugin.json` says `2.0.0` but `package.json` says `1.9.0` in what should be a unified version. **Stop and ask.** Show the mismatch table and let the user decide how to resolve.

### 3. Determine New Version

1. Get commits since last tag:
   ```bash
   git log $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --oneline --no-decorate
   ```

2. **Investigate changes in detail.** Examine actual diffs — commit prefixes can be misleading:
   ```bash
   git diff $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --stat
   ```
   Read the full diff for commits touching public APIs, interfaces, or config formats. Breaking change signals by stack:
   - **Rust**: removed/renamed public items, changed function signatures, MSRV bump, removed features
   - **Python**: removed/renamed public functions/classes, changed function signatures, dropped Python version support
   - **JS/TS**: removed/renamed exports, changed function signatures, dropped Node version support
   - **Plugin**: removed/renamed agents or skills, changed frontmatter interfaces, removed components
   - **Any**: changed config formats, removed CLI flags, changed data schemas

3. If bump type was provided as argument, use it. Otherwise auto-detect:
   - **major**: breaking changes in diffs, `BREAKING CHANGE` in body, or type suffix `!`
   - **minor**: new features in diffs, or `feat:` commits
   - **patch**: only fixes, refactors, docs, CI
   - Default to `patch` if unclear

4. Apply bump: `major` -> X+1.0.0, `minor` -> X.Y+1.0, `patch` -> X.Y.Z+1

5. **Present analysis and ask for confirmation.** Show:
   - Current version -> proposed version (bump type)
   - Commit list with short descriptions
   - Key changes from diff investigation
   - Justification for bump type
   - Version files that will be updated
   - Post-bump commands that will run (lock file syncs, etc.)
   - Options: proposed bump (recommended), alternative bumps, or abort

### 4. Update Version Files

Update ALL version files detected in Step 1 (within confirmed scope from Step 2).

Then sync lock files:
- **Rust**: `cargo update --workspace` (required — `cargo publish --locked` fails otherwise)
- **JS/TS**: run the project's package manager (`npm install`, `yarn install`, or `pnpm install`) to sync lock file
- **Python**: no lock file sync typically needed (but check for `poetry.lock` -> `poetry lock`)

### 5. Generate Changelog Entry

If `CHANGELOG.md` exists, prepend new entry after the header. If absent, create it.

Format per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):

```markdown
## [X.Y.Z] - YYYY-MM-DD

### BREAKING
- description (hash)

### Added
- description (hash)

### Fixed
- description (hash)

### Changed
- description (hash)
```

Commit-type mapping:

| Commit prefix | Changelog section |
|---|---|
| `feat` | Added |
| `fix` | Fixed |
| `perf`, `refactor`, `docs` | Changed |
| `chore`, `ci`, `build`, `test`, `style` | Other |
| `BREAKING CHANGE` or `!` suffix | BREAKING |

Omit empty sections. Strip type prefix and optional scope from descriptions. Non-conventional commits go in Changed.

If the file has compare links at the bottom, add: `[X.Y.Z]: https://github.com/{owner}/{repo}/compare/v{old}...vX.Y.Z` (derive owner/repo from `git remote get-url origin`).

### 6. Commit and Push

Stage all modified version files, lock files, and `CHANGELOG.md`:
```bash
git add {all_changed_files}
git commit -m "chore: release v{new}"
git push
```

Verify push succeeds before proceeding.

### 7. Create GitHub Release

Write the new changelog entry (just this version, not the full file) to a temp file, then:
```bash
gh release create v{new} --title "v{new}" --notes-file {changelog_temp_file}
```

Print the release URL.

### 8. Summary

Print:
- Version: {old} -> {new}
- Updated files (list)
- Release URL
- Triggered workflows (if known from CI config — e.g., publish to crates.io, npm, PyPI, Docker)

## Constraints

- **User-only** — this skill must never be invoked by agents autonomously.
- NEVER create the release before pushing — the tag must reference a remote commit.
- NEVER skip lock file sync — downstream installs will break.
- If any step fails, stop and report. Do not continue with partial state.
- If versions are inconsistent and user hasn't confirmed scope, do not proceed.
