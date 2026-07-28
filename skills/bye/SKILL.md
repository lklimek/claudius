---
name: bye
description: "This skill should be used when the user says \"bye\", \"wrap up\", \"tear down\", \"we're done\", or otherwise ends the session. It shuts down spawned teammates and agents, removes their worktrees, and reconciles uncommitted or unpushed session work."
---

# bye

1. Shut down every teammate/background agent spawned this session (per `grand-admiral` shutdown discipline — never `TaskStop` a named teammate).
2. For each worktree created this session: check `git status`/`git log` vs its base. Fully merged and clean → `git worktree remove` + delete its branch. Anything uncommitted or unmerged → do NOT delete; handle per step 3.
3. Sweep every repo/worktree touched or created this session (main cwd(s) plus anything from step 2) for uncommitted changes or unpushed commits. For each:
   - Correct action obvious (e.g. finish a trivial commit, merge an already-reviewed branch) → do it.
   - Otherwise → escalate to the user: what's dangling, where, your recommendation. Never guess on anything destructive or ambiguous.
4. In the main session checkout(s), once step 3 is clean (no uncommitted/unpushed work left unresolved): `git fetch` then `git pull --no-rebase` to bring the checked-out branch up to date with origin. Skip a checkout still holding escalated work — don't pull over it.
5. Report a final summary: what was torn down, what was fixed, what's escalated.
