# Stacked PRs

A stack is a linear chain of PRs in one repository: the bottom PR targets the base branch, each other PR targets the branch of the PR below it. Two kinds exist; never mix their update rules.

## Detect the kind

`gh api graphql -f query='{ repository(owner:"<o>",name:"<r>"){ pullRequest(number:<n>){ baseRefName stack { number size baseRefName } } } }'` — non-null `stack` → **native**; null with `baseRefName` ≠ the default branch → **manual**. Locally, `gh stack view --json` (exit 2 = branch not in a local stack).

## Choosing

New stacks are **native** ([GitHub stacked PRs](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs), `gh extension install github/gh-stack`). Use **manual** only where native is unavailable: forks, GitHub Enterprise Server, exit code 9 (stacked PRs unavailable), or a non-linear (tree) dependency. Existing manual stacks stay manual unless the user asks to convert them (`gh stack link <pr>...`, linear history required).

## Native stacks

Follow the upstream agent skill ([gh-stack SKILL.md](https://github.com/github/gh-stack/blob/main/skills/gh-stack/SKILL.md)): non-interactive forms only (`view --json`, `submit --auto`, `init <branch>...`, `add <branch>`, `checkout <target>`, `up`/`down`/`top`/`bottom`; never `modify`, `switch`, or `gh pr merge` on a stack), state from `--json` and exit codes, and each change committed on the layer that owns it.

- **History rewriting is allowed here** — the exception to `git-and-github` Safety Rule 2, coordinator-only and only on the stack's own branches: `gh stack rebase`, `gh stack sync`, and `gh stack push` (per-branch `--force-with-lease`). Never `git push --force` by hand and never amend.
- **Updating**: never merge the base or a parent into a native branch — a merge commit breaks the linear history the stack needs to merge. A fix is committed and pushed on its own layer alone — never cascaded because a lower layer or trunk moved. Rebase the upper layers (`gh stack rebase --upstack`, then `gh stack push`) only when one of them is pushed for its own changes, `view --json` reports `needsRebase` before a merge, or the user asks. `gh stack sync` onto a moved trunk only on those last two — never because a layer, the bottom included, is pushed. When GitHub retargets the stack after its base branch is deleted, pass `--accept-base-change` only if the old base merged; otherwise stop and ask the user — its commits would be dropped.
- **Conflicts** (exit 3): resolve, `git add`, `gh stack rebase --continue`; unresolvable → `--abort` and report.
- **Merging** is user-only (Safety Rule 8): `gh stack merge <pr-or-stack> --yes` lands bottom-up; the PRs above retarget automatically. Drafts cannot merge.
- **Restructuring** (reorder, remove a layer) is user-only: `gh stack unstack`, then `gh stack init`.
- Rewrites touch clean worktrees only: keep every worktree on a stack branch idle while the coordinator rebases or syncs.

## Manual stacks

The `git-and-github` § Before Every Push gate's base is the parent branch, merged in only when the stacked PR is pushed for its own changes. Never cascade a parent change up the stack: the bottom PR merges first, then the next PR is updated from the base branch, and so on up. Agents never merge a parent into a stacked branch on their own; the coordinator resets such a stray merge to the branch's pushed head when it holds no other unpushed work. Retargeting and unstacking are user-only (Safety Rule 8).
