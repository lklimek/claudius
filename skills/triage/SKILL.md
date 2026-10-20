---
name: triage
description: "This skill should be used when the user says \"triage\" or asks to triage a GitHub issue: reproduce it, identify the root cause and owning component, estimate severity, discuss the findings with the user, and then post a short status comment."
argument-hint: <issue-number-or-url>
---

# Triage

1. Fetch the issue ($ARGUMENTS). Resolve this repo's stable/release branch — check its `CLAUDE.md`/docs for a documented convention first; otherwise use the GitHub default branch (`gh repo view --json defaultBranchRef`). Check the issue against it.
2. Reproduce and root-cause per `claudius:bug-investigation`. Prefer a unit/integration test using the project's own test command. For GUI-only issues, use a GUI-automation skill if one is available in this environment, or the project's own GUI-testing docs; otherwise ask the user how to reproduce it.
3. Attribute the root cause to its owning component (crate/package/module). For dependency defects, follow [bug-investigation](../bug-investigation/SKILL.md) § Rules, including its user-decision gate regardless of repository ownership.
4. Estimate severity with `claudius:severity`; report it to the user.
5. Discuss repro, root cause, owning component, and severity with the user — before any GitHub write.
6. Root cause in a dependency → follow the user's chosen course; file or link an issue only if authorized. Root cause in this project's own code → normal fix flow.
7. On the user's go-ahead: comment on the issue — status update, ≤200 characters, plus links to anything filed/related. Every GitHub write needs sign-off first (`claudius:git-and-github` Safety Rules).
