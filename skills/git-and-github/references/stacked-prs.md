# Stacked PRs

A stack is a linear chain of PRs in one repository: the bottom PR targets the base branch, each other PR targets the branch of the PR below it. Two kinds exist; never mix their update rules.

## Detect the kind

`gh api graphql -f query='{ repository(owner:"<o>",name:"<r>"){ pullRequest(number:<n>){ baseRefName stack { number size baseRefName } } } }'` — non-null `stack` → **native**; null with `baseRefName` ≠ the default branch → **manual**. Locally, `gh stack view --json` (exit 2 = branch not in a local stack).

## Choosing

New stacks are **native** ([GitHub stacked PRs](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs), `gh extension install github/gh-stack`). Use **manual** only where native is unavailable: forks, GitHub Enterprise Server, exit code 9 (stacked PRs unavailable), or a non-linear (tree) dependency. Existing manual stacks stay manual unless the user asks to convert them (`gh stack link <pr>...`, linear history required).

## Native stacks

Follow the upstream agent skill ([gh-stack SKILL.md](https://github.com/github/gh-stack/blob/main/skills/gh-stack/SKILL.md)): non-interactive forms only (`view --json`, `link`, `init <branch>...`, `add <branch>`, `checkout <target>`, `up`/`down`/`top`/`bottom`; never `modify`, `switch`, or `gh pr merge` on a stack), state from `--json` and exit codes, and each change committed on the layer that owns it.

- **History rewriting is allowed here** — the exception to `git-and-github` Safety Rule 2, coordinator-only and only on the stack's own branches: the single-layer rebase below, `gh stack rebase`, `gh stack sync`, and `gh stack push`. Every forced push carries a lease; never amend.
- **Creating PRs**: push the layer alone (§ Updating), `gh pr create --draft --base <parent>`, then `gh stack link <stack-number> <pr>` (new stack: `gh stack link <pr>...`, bottom to top). Pass PR numbers only — branch arguments, like `gh stack submit`, push every layer.
- **Updating**: never merge the base or a parent into a native branch — a merge commit breaks the linear history the stack needs to merge. Integrate agent commits by cherry-pick or fast-forward only; `git log --merges <remote>/<parent>..<branch>` must be empty before a push. Before every push of a layer, apply the § Before Every Push gate to its parent (the bottom layer's is trunk) by rebasing that layer alone onto it: `git rebase --onto <remote>/<parent> <old-parent> <branch>`, `<old-parent>` being the parent commit the layer was built on (`git merge-base --fork-point <remote>/<parent> <branch>`; not found → stop and ask), then `git push --force-with-lease=<branch>:<pushed-sha> <remote> <branch>`. Never propagate to the layers above — each takes the change when pushed for its own changes. Cascade (`gh stack sync`, or `gh stack rebase`, then `gh stack push`) only when `view --json` reports `needsRebase` before a merge, or the user asks. When GitHub retargets the stack after its base branch is deleted, pass `--accept-base-change` only if the old base merged; otherwise stop and ask the user — its commits would be dropped.
- **Conflicts**: resolve, `git add`, then `git rebase --continue`, or `gh stack rebase --continue` for a paused `gh stack rebase` (exit 3); unresolvable → `--abort` and report. `gh stack sync` exit 3 restores every branch: run `gh stack rebase` to reproduce the conflict ([troubleshooting](https://github.com/github/gh-stack/blob/main/skills/gh-stack/references/troubleshooting.md)).
- **Merging** is user-only (Safety Rule 8): `gh stack merge <pr-or-stack> --yes` lands bottom-up; the PRs above retarget automatically. Drafts cannot merge.
- **Restructuring** (reorder, remove a layer) is user-only: `gh stack unstack`, then `gh stack init`.
- Rewrites touch clean worktrees only: keep every worktree on a stack branch idle while the coordinator rebases or syncs.

## Manual stacks

The `git-and-github` § Before Every Push gate's base is the parent branch, merged in only when the stacked PR is pushed for its own changes. Never cascade a parent change up the stack: the bottom PR merges first, then the next PR is updated from the base branch, and so on up. Agents never merge a parent into a stacked branch on their own; the coordinator resets such a stray merge to the branch's pushed head when it holds no other unpushed work. Retargeting and unstacking are user-only (Safety Rule 8).
