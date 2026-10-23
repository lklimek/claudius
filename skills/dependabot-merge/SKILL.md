---
name: dependabot-merge
description: "This skill should be used when the user asks to \"merge dependabot PRs\", \"process dependency bumps\", \"auto-merge bot PRs\", or \"handle the dependabot backlog\". It audits each dependency, comments findings, merges when CI is green, and requests rebases for conflicts or CI failures."
user-invocable: true
allowed-tools: Read, Grep, Glob, Bash(gh pr *), Bash(gh run *), Bash(git log *), Bash(git branch *), Bash(git status *), Bash(ghsudo *), Agent, Skill
---

# Dependabot PR Bulk Processor

Audit, comment, and merge open dependabot PRs. Each PR gets a security review via the `review-dependency` skill, a comment with findings, and — if safe — a squash merge.

**Argument**: `$ARGUMENTS` — optional filter (e.g., `golang`, `docker`, `npm`). Empty = process all open dependabot PRs.

## Prerequisites

`ghsudo` (`pip install ghsudo`) for write operations; `review-dependency` skill.

## Workflow

### 1. Discover Open Dependabot PRs

```bash
gh pr list --repo <owner>/<repo> --author 'app/dependabot' \
  --json number,title,statusCheckRollup,mergeable --limit 50
```

Extract per PR: number, title, CI status (which checks passed/failed), mergeable state. If `$ARGUMENTS` is set, keep only PRs whose title contains it.

### 2. Check for Unpushed Commits

`git log @{upstream}..HEAD --oneline` (no upstream: `git log origin/$(git branch --show-current)..HEAD`). Unpushed commits → **alert the user and stop** — worktree agents fork from remote state and would miss them.

### 3. Classify PRs

| Group | Condition | Action |
|---|---|---|
| **Green** | All CI checks passed + MERGEABLE | Audit, Comment, Merge |
| **Red** | CI failures + MERGEABLE | Audit, Comment, `@dependabot rebase` |
| **Conflicting** | CONFLICTING mergeable state | Comment conflict notice, `@dependabot rebase` |

Present the classification table to the user and **ask for confirmation** before proceeding.

### 4. Dispatch Dependency Reviews

Load [delegate](../delegate/SKILL.md) and [grand-admiral](../grand-admiral/SKILL.md). For each PR, prepare an isolated worktree at the verified PR revision and dispatch a generic worker through the host's native tools. Supply the absolute worktree path as its working directory and explicit skill paths. Don't request `bypassPermissions`: Claude Code (≥ 2.1.267) runs a subagent in it only when the main session already is. Without matching allow rules a worker's `gh` writes may be denied; §5 then has the coordinator post and merge.

Use a strong available reasoning model for every dependency bump per `delegate` § Token Economy. A passing vulnerability scan is not evidence of low risk; fully investigate the changed third-party source.

**Agent prompt must include ALL of:**
1. PR number, title, repo `<owner>/<repo>`
2. CI status — green or red, which checks failed
3. Mergeable state
4. Instruction to invoke `claudius:review-dependency` through the Skill tool (it runs forked and returns the report; on hosts without it, load [review-dependency](../review-dependency/SKILL.md)), with the PR diff, package names, and version range as context
5. Instruction to post a comment with findings via `gh pr comment <number> --repo <owner>/<repo> --body-file <file>` (include attribution footer; `ghsudo` on 403), and to report back either "confirmed posted: `<comment URL>`" or "NOT posted: `<reason>`" — never a bare "published"/"done", which has been observed meaning only "returned the text to you"
6. **If Green**: merge via `ghsudo gh pr merge <number> --repo <owner>/<repo> --squash`
7. **If Red or Conflicting**: do NOT merge; post `@dependabot rebase`, then enter **Rebase Watch Loop** (step 5a)

Bound concurrency by actual host capacity. Each `review-dependency` invocation dispatches its own security reviewer: reserve capacity for that child before starting a PR worker, and queue remaining PRs. If capacity permits only a coordinator and one reviewer, run the dependency workflow in the coordinator and dispatch its security pass directly. Collect every result before ending the turn.

### 5. Collect Results and Handle Write Blocks

**Never trust a "posted"/"published" self-report** — confirmed: an agent reported a comment published when the PR had zero comments, and stated unverified claims (signature checks, release immutability) as fact. Verify with `gh pr view <number> --json comments` for an actual comment from this run, and re-read the agent's reasoning for anything phrased as fact it did not check. Where an agent's GitHub write failed or verification fails: post the comment and execute the merge/rebase/watch loop yourself.

### 5a. Rebase Watch Loop

After posting `@dependabot rebase`, poll until the rebase lands and CI completes (or timeout).

1. Record the current HEAD SHA before requesting rebase
2. Poll every 60s (max 15 minutes):
   ```bash
   gh pr view --repo <owner>/<repo> <number> --json headRefOid,statusCheckRollup,mergeable
   ```
3. Exit conditions:

| Condition | Action |
|---|---|
| `headRefOid` changed + all checks `SUCCESS` + `mergeable == MERGEABLE` | Squash merge via `ghsudo gh pr merge` |
| `headRefOid` changed + any check `FAILURE` | Report as **CI Red after rebase** — do NOT re-rebase |
| 15 min elapsed, HEAD unchanged | Report as **Rebase Timeout** |
| Merge attempt fails (race, new conflict) | Report as **Merge Failed after rebase** |

On successful merge, report as **Merged after rebase**.

### 6. Handle Cascading Merge Failures

After earlier PRs merge, later PRs may become unmergeable (conflicting `go.sum`, lock files, etc.). When a merge fails with "not mergeable":
1. Post `@dependabot rebase` on the PR
2. Enter **Rebase Watch Loop** (step 5a) — same timeout and CI check logic

### 7. Final Report

| PR | Dependency | Audit | Action | Result |
|---|---|---|---|---|
| #NNN | `pkg` old->new | Safe/Risk | Merged/Rebase/Skipped | OK/MERGED_AFTER_REBASE/CI_RED/TIMEOUT/MERGE_FAILED/WARN |

Include:
- Total merged count (direct + after rebase)
- Rebase outcomes: merged after rebase, CI red after rebase, rebase timeout, merge failed after rebase
- Any PRs with security concerns (not merged)
- Note flaky tests if multiple PRs failed the same test

### 8. Lessons Learned

After all PRs, invoke `claudius:lessons-learned` skill if notable patterns emerged (flaky tests blocking merges, recurring merge conflicts, security concerns).

## Safety Rules

- Every GitHub comment ends with the attribution footer from `git-and-github`
- Never merge a PR with security concerns (comment only) or failing CI (request rebase)
- User confirmation before starting the bulk operation
- `ghsudo` for writes when `gh` alone fails with 403/404; exit 2 (user denied) → skip that PR; exit 4 (no token) → ask the user to run `ghsudo --setup <org>`
