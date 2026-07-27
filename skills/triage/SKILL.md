---
name: triage
description: "Use when the user says \"triage\" or asks to triage a GitHub issue: reproduce, root-cause, attribute to the owning component, estimate severity, discuss with the user, then post a short status comment."
argument-hint: <issue-number-or-url>
---

# Triage

1. Fetch the issue ($ARGUMENTS). Resolve this repo's stable/release branch — check its `CLAUDE.md`/docs for a documented convention first; otherwise use the GitHub default branch (`gh repo view --json defaultBranchRef`). Check the issue against it.
2. Reproduce and root-cause per `claudius:bug-investigation`. Prefer a unit/integration test using the project's own test command. For GUI-only issues, use a GUI-automation skill if one is available in this environment, or the project's own GUI-testing docs; otherwise ask the user how to reproduce it.
3. Attribute the root cause to its owning component (crate/package/module). If it traces into a git-pinned or vendored dependency, resolve that dependency's own repository. Same GitHub org/owner as this repo → treat as ours to potentially fix; different org → external, note it and stop there.
4. Estimate severity with `claudius:severity`; report it to the user.
5. Discuss repro, root cause, owning component, and severity with the user — before any GitHub write.
6. Root cause in another same-org repo → propose filing an issue there (confirm with user first), link it from this one. Root cause in this repo → normal fix flow.
7. On the user's go-ahead: comment on the issue — status update, ≤200 characters, plus links to anything filed/related. Every GitHub write needs sign-off first (`claudius:git-and-github` Safety Rules).
