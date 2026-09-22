---
name: bug-investigation
description: "This skill should be used when investigating a reported bug, diagnosing a failure, or performing root-cause analysis — especially before concluding \"not a bug\", tracing a symptom, or explaining unexpected behavior. Preloaded on investigation agents."
user-invocable: true
---

# Bug Investigation

Default discipline for diagnosing a reported bug. The user's reproducible observation is ground truth — the analysis must explain it, not explain it away.

## Rules

1. **Observation over theory** — the user's reproducible facts are ground truth to explain; their causal explanation is only a hypothesis. Refuting the theory ≠ explaining the observation. (User imprecision usually lives in the explanation, not the observation.)
2. **Entry point over name** — statically trace the call graph from the actual UI/CLI entry point (the thing the user clicked/ran) down to the outcome. Never anchor on a function whose name merely matches the feature.
3. **The exercised path, not a correct path** — when ≥2 plausible code paths exist, verify the one actually hit. Proving a correct path exists is not proving the user's path is correct.
4. **Reproduce or it's unsolved** — analysis that cannot reproduce the user's concrete observation is INCOMPLETE. Never conclude "not a bug" until the observation is explained. A clash between analysis and a user-observed fact is a STOP signal, not a footnote. When the repro artifact is a test, it must be RED against the documented contract on the buggy revision, not green mirroring the defect — see `coding-best-practices` § Workflow Discipline TDD "Repro tests go RED first".
5. **Brief with the literal reproduction** (coordinator-facing) — investigation spawn prompts MUST quote the user's exact reproduction steps and the literal entry point, and require: "trace from this entry point; if you can't reproduce the observed symptom, you haven't found the cause."

## Failure Mode (real case)

A funds-safety bug (receive address derived past the SPV gap window → invisible funds) was cleared as "not a bug" by violating all four rules: anchored on the user's gap-limit THEORY instead of the OBSERVATION (button → index 32 → funds missing); traced `next_receive_address` by name instead of from the UI button → `add_receiving_address` → legacy `Wallet::receive_address`; proved a correct path exists rather than the one the button calls; rationalized away an index-32-vs-claimed-0 contradiction instead of stopping. Only a user-supplied on-chain reproduction caught it.

## Composition

Complements `coding-best-practices` "Verify facts before acting on broad instructions" (broad user directives vs. premature diagnostic conclusions). This is a FORWARD trace (entry point → symptom); the BACKWARD direction (which callers a changed function breaks) is `grumpy-review`'s `references/call-tree-walk.md`.
