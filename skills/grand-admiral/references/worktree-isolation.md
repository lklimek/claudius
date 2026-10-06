# Worktree Isolation — Reference

Detail behind `grand-admiral` § Worktree Isolation. Read when a base cannot be injected by SHA, an agent lands outside its worktree, a worktree disappears, or before the post-wave merge.

## Base sync options

- **Option A (default — local-SHA injection, no push):** capture `git rev-parse HEAD` (never a branch name or symbolic ref — they resolve differently in worktrees) and inject: `"Your worktree may be behind local HEAD. As your FIRST action, run: git merge --ff-only <sha>"`. Worktrees share the object store, so unpushed commits are reachable by SHA. Default because it avoids noisy partial pushes and keeps work local until a wave is verified.
- **Option B (fallback — push first):** `git log @{upstream}..HEAD --oneline`; if unpushed commits exist or no upstream is configured, push, then fork from `origin/<branch>`. Only when origin is genuinely required (cross-machine work, PR-gated CI, cross-session sharing). Anti-pattern: committing locally without pushing, then launching Option B agents that need those commits.

## `isolation` flag — KNOWN BROKEN

Silently dropped for team spawns (`Agent(team_name=..., isolation="worktree")` is ignored; omitting `team_name` doesn't help — every `Agent()` from a team-lead session auto-joins the team) AND for standalone `run_in_background` spawns (two background agents landed in the main repo, switched its branch, and left uncommitted edits). Symptom: `pwd` returns the main repo path, not the assigned worktree. An in-prompt `pwd` self-check alone is NOT sufficient — agents may proceed anyway; lead pre-creation is the only reliable guarantee.

## Vanishing worktrees

A pre-created worktree can vanish mid-session (cause unconfirmed), silently falling back to the parent's real checkout on whatever branch it has. Hence the fail-closed `pwd` re-check before EVERY git write command: refuse the write and report the mismatch rather than proceed against the real checkout.

## Post-wave

Enumerate worktrees → verify commits → cherry-pick/merge into the feature branch → run the contributing agents' scopes → clean up (`git worktree remove` + `prune`).

- Never remove a worktree with uncommitted or unmerged work.
- Verify the current branch before cherry-picking and again after cleanup — `git worktree remove` can leave the session on the worktree's branch.
- Use absolute paths with `git -C`.
- Delete stale worktree branches (`git branch -D`) — they accumulate fast.
- Before deleting or recreating a worktree assumed abandoned, verify the owning agent's pane/process is idle or gone.
