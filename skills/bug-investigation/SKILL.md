---
name: bug-investigation
description: Use when investigating a reported bug, diagnosing a failure, or doing root-cause analysis — especially before concluding "not a bug", tracing a symptom, or explaining unexpected behavior. Preloaded on investigation agents.
user-invocable: true
---

# Bug Investigation

Default discipline for diagnosing a reported bug. The user's reproducible observation is ground truth — the analysis must explain it, not explain it away.

## Rules

1. **Observation over theory** — the user's reproducible facts are ground truth to explain; their causal explanation is only a hypothesis. Refuting the theory ≠ explaining the observation. (User imprecision usually lives in the explanation, not the observation.)
2. **Entry point over name** — statically trace the call graph from the actual UI/CLI entry point (the thing the user clicked/ran) down to the outcome. Never anchor on a function whose name merely matches the feature.
3. **The exercised path, not a correct path** — when ≥2 plausible code paths exist, verify the one actually hit. Proving a correct path exists is not proving the user's path is correct.
4. **Reproduce or it's unsolved** — if your analysis cannot reproduce the user's concrete observation, it is INCOMPLETE. Never conclude "not a bug" until the observation is explained. A clash between your analysis and a user-observed fact is a STOP signal, not a footnote.
5. **Brief with the literal reproduction** (coordinator-facing) — investigation spawn prompts MUST quote the user's exact reproduction steps and the literal entry point, and require: "trace from this entry point; if you can't reproduce the observed symptom, you haven't found the cause."

## Failure Mode (worked example)

A real funds-safety bug (a receive address derived past the SPV gap window → invisible funds) was wrongly cleared as "not a bug"; only a user-supplied on-chain reproduction caught it.

| Rule violated | What went wrong |
|---|---|
| Rule 1 | Anchored on the user's gap-limit THEORY instead of the OBSERVATION (button → index 32 → funds missing) |
| Rule 2 | Traced `next_receive_address` (a correct backend path) by name instead of from the UI button → `add_receiving_address` → legacy `Wallet::receive_address` |
| Rule 3 | Proved a correct path exists rather than checking the path the button actually calls |
| Rule 4 | Noticed an index 32 vs claimed 0 contradiction and rationalized it away instead of stopping |

## Composition

- Complements `coding-best-practices` § Cross-Cutting Rules "Verify facts before acting on broad instructions" (that rule is about broad user directives; this skill is about not concluding prematurely during diagnosis).
- This is a FORWARD trace (entry point → symptom); for the BACKWARD direction (which callers a changed function breaks) see `grumpy-review`'s `references/call-tree-walk.md`.
