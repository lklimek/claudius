---
name: release
description: "This skill should be used when the user asks to \"bump the version\", \"cut a release\", or \"create a GitHub release\". It applies SemVer 2.0, updates the changelog, commits, pushes, creates the release, and auto-detects Rust, Python, JS/TS, Claude Code plugin, and other supported stacks. Arguments are major, minor, patch, or auto-detection from commits. User-invocable only — agents must not invoke it autonomously."
user-invocable: true
disable-model-invocation: true
---

# Release

Load `claudius:git-and-github` first — all commit, push, and PR conventions come from there. Optional argument: `major`, `minor`, or `patch`; if omitted, auto-detect from git history. If any step fails, stop and report — never continue with partial state.

## Steps

1. **Pre-flight** — the working tree must be clean (dirty → stop and ask). On a feature branch, warn and ask whether to release from here or switch to the base branch first.
2. **Detect version files** — every version-carrying file in the repo: `Cargo.toml` (root, workspace, and members), `pyproject.toml`, `setup.py`/`setup.cfg`, `package.json` (root + workspaces), `lerna.json`, `.claude-plugin/plugin.json`, `version.txt`/`VERSION`. None found → stop and ask.
3. **Validate consistency** — all identical → proceed. Intentionally independent (workspace members with explicit versions, lerna `"independent"`) → list each component and version, ask which to release. Unexpectedly inconsistent → stop, show the mismatch table, let the user decide; do not proceed without a confirmed scope.
4. **Determine the new version** — commits since the last tag (`git describe --tags --abbrev=0`; none → from the root commit). **Read the actual diffs** of commits touching public APIs, interfaces, or config formats — commit prefixes can mislead. Use the argument if given, else SemVer 2.0 from what the diffs show: **major** for breaking changes (also `BREAKING CHANGE` in a body or a `!` type suffix), **minor** for new features (`feat:`), **patch** for fixes/refactors/docs/CI and when unclear. **Ask for confirmation**: current → proposed version, commit list, key diff findings, justification, files to update; offer the proposal, alternatives, and abort.
5. **Update version files** within the confirmed scope, then sync every lock file with its package manager (`cargo update --workspace`, the matching npm/yarn/pnpm install, `poetry lock`). NEVER skip lock file sync.
6. **Changelog** — prepend the entry, covering every change merged since the previous entry, to `CHANGELOG.md` (create if absent) per [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); add a compare link if the file uses them.
7. **Commit and push** — version files, lock files, `CHANGELOG.md`; message `chore: release v{new}`. Verify the push succeeded before continuing.
8. **Create the GitHub release** — only after the push, so the tag references a remote commit. Write this version's changelog entry to a temp file: `gh release create v{new} --title "v{new}" --notes-file {changelog_temp_file}`.
9. **Summary** — version change, updated files, release URL, triggered workflows (if known from CI config).
