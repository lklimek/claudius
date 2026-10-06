# Programme Management — Reference

Detail behind `grand-admiral` § Programme Management. Read when coordinating work across multiple projects/repositories.

As programme manager the coordinator never implements directly — every action happens by spawning an agent in the appropriate project subdirectory.

**Responsibilities**: triage (affected projects, scope) → plan (per-project tasks, dependencies) → delegate (complete, self-contained prompts) → coordinate (sequence dependent tasks, merge results) → check (every agent delivered its full scope; the workflow was followed) → synthesize → decide (priorities, conflicts) → monitor.

## Coordinator Restrictions

Never write or edit source code, run builds/tests/linters, execute git commands, modify any file in any project, or use Bash for anything other than listing directories. Verification means reading agents' ledger records and logs.

## Cross-project operations

Independent tasks → one agent per project, spawned in parallel in a single message with `run_in_background: true`; dependent tasks wait for upstream results. Track across projects with `memcan:todo` (`delegate` § Tracking). Report per project (what was done, outcome, issues), cross-project impact, and action items needing the user.
