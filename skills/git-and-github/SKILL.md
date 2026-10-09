---
name: git-and-github
description: "This skill should be used when running git or gh commands, interacting with GitHub, or resolving git and gh access or permission-denied failures. It defines commit, push, PR, issue, and review conventions, the attribution footer, and the safety rules for publishing."
---

# GitHub Workflow

**Tooling**: `git` for repository operations; `gh` CLI and the `scripts/gh-*.sh` wrappers for all GitHub API operations — see [gh-cli.md](references/gh-cli.md) for the wrapper catalog, `ghsudo` usage, and exit codes.

**Attribution**: every commit, PR, issue, and comment posted to GitHub **must** include this footer (blank line before it):

```
<sub>🤖 Co-authored by [Claudius the Magnificent](https://github.com/lklimek/claudius) AI Agent</sub>
```

## Before Starting Work

1. Verify you're on a base branch — if on an unrelated feature branch, switch to base or confirm with user.
2. Pull (fast-forward only). On diverged history, rebase if trivial, otherwise alert user.
3. Search open PRs for related fixes — don't duplicate in-progress work.

## Committing

Create feature branches; NEVER commit to a base branch. [Conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`; `!` for breaking changes), message passed via HEREDOC, ending with the trailer `Co-Authored-By: Claude <your-model-name> <noreply@anthropic.com>` — your actual current model, never a version copied from a doc. Never create or edit `CHANGELOG.md` in a feature PR — concurrent PRs conflict on it; it is written at release time (`release` skill). Exception: a project policy that explicitly requires a per-PR entry.

## Pull Requests

### Creating a PR

Check for a PR template first; if one exists, fold its required content into the skeleton linked below rather than replacing it.

The PR body **must lead with a plain-language summary before any implementation detail** — a technical product manager or external reviewer with no code context must understand everything before `Detailed discussion` at a glance. Fill in the skeleton from [pr-body-template.md](references/pr-body-template.md) (fenced block only, not the page's title or prose).

**`TL;DR` / `User story` / `Scenario` are user-facing** — plain language only: no specialized terms, internal implementation details, or code identifiers. Describe strictly user-observable behavior (for an API/CLI, the calling developer *is* the user). `User story` uses the same "As a `<role>`..." shape as Issues below, phrased for a change already made. `Scenario` isn't only for bugs: for a new feature, `Actual behavior` is what's missing/impossible today, `Expected behavior` is what becomes possible after this PR — no failure required. For a pure internal change with no user-observable effect, drop `User story` and `Scenario` and say so in `Detailed discussion`. Note blocking relationships (prerequisite for / depends on / stacked atop PR #N) in `Detailed discussion`.

**`Detailed discussion` is for implementors and AI agents** — as technical as needed.

`TL;DR` → `User story` → `Scenario` → `Detailed discussion`, in that order. Always create PRs as drafts.

**PR descriptions describe net final state only** — no development history, changelog, or iteration/debugging narrative; that belongs in commit messages. `### Actual behavior` (the pre-existing problem being solved) and concise final `### Testing` results describe state, not history, and are expected.

### Reviewing a PR

**Never submit a final review (approve/request-changes). Always create draft/pending reviews** — the user publishes them. Before posting any review comment, read [pr-review.md](references/pr-review.md): fetching PR context, deduplication, diff-bounds verification, inline comments.

### Issues

Before creating, search existing issues (open + closed) and PRs for duplicates — if found, show the user and ask before proceeding. If an issue template exists, fold its required content into the skeleton rather than replacing it.

Issue bodies use the same plain-language-first skeleton as PRs (see §Creating a PR): fill in [issue-body-template.md](references/issue-body-template.md) (fenced block only) — `TL;DR` → `User story` → `Scenario` → `Detailed discussion`. `User story`: "As a **\<role\>**, I want to ..., to achieve ..." — multiple personas fine, repeat the line. Append the attribution footer last.

### Requesting Reviewers

`${CLAUDE_PLUGIN_ROOT}/scripts/gh-request-reviewer.sh <owner/repo> <pr_number> <reviewer> [reviewer ...]` for every reviewer request (multiple reviewers, `@copilot`). `@copilot` requires `gh` ≥ 2.88.0 — on failure, check `gh --version` and escalate to the user if an upgrade is needed.

## Safety Rules

1. **Pushing is coordinator-only.** Spawned/specialist agents never push — they commit and stop, and the coordinator pushes on their behalf. A coordinator push to a feature branch needs no confirmation, its own discretion. Publishing anything else to GitHub (PRs, issues, comments, reviews) still requires explicit confirmation, even if the user agreed earlier. **Never push to a base/protected branch** (main, master, vX.Y-dev, or whatever the repo's configured base is) — that's not a confirmation gate, it's an outright block; if a base-branch push is ever genuinely warranted, the human does it.
2. **Never force-push. Never amend commits.** Always create new commits. If force-push is needed, ask the user to do it manually.
3. **Never `git add .` or `git add -A`** — stage specific files; check for `.env`, credentials, or secret files before staging and warn if found.
4. **Never use interactive flags** (`-i`); **never skip hooks** (`--no-verify`) unless explicitly requested.
5. **Avoid `gh api`** — prefer high-level `gh` subcommands and the wrapper scripts. Use `gh api` only for read-only queries with no subcommand equivalent (with `--jq`, not `| jq` — `!` triggers shell history expansion); never for writes. Exception: `gh api graphql` for mutations with no CLI equivalent (e.g., thread resolution).
6. **Never fork repositories** — forking creates a separate repo and breaks the workflow. On 403/404 or "Resource not accessible" from `gh` or `git push`, retry the same command through [ghsudo](https://github.com/lklimek/ghsudo) if installed, else ask the user.
7. **Sandbox**: `gh`/`ghsudo` need network access to `api.github.com`. Preferred fix: add `"api.github.com"` to `sandbox.network.allowedDomains` in `settings.json`. If unconfigured and `gh` fails with network errors, fall back to `dangerouslyDisableSandbox: true` on the Bash call.

## Context Management — Large GitHub Responses

`gh` output can run 10k+ tokens (file lists, diffs, review threads, CI logs). Delegate unbounded calls — `gh pr diff`, `gh pr view --json files`, `gh-fetch-review-comments.sh`, `gh run view --log`, `gh * list`/`gh search *` with many results — to a disposable subagent that returns a concise summary (`Explore` for read-only extraction, `general-purpose` when writes are needed), telling it exactly what to extract and in what format. Bounded calls (single `gh pr view`/`gh issue view` with selected `--json` fields, single commit) are fine directly.
