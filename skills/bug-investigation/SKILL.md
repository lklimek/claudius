---
name: bug-investigation
description: "This skill should be used when investigating a reported bug, diagnosing a failure, or performing root-cause analysis — especially before concluding \"not a bug\", tracing a symptom, or explaining unexpected behavior. It makes the reported observation the ground truth to reproduce and traces from the real entry point. Preloaded on investigation agents."
user-invocable: true
---

# Bug Investigation

Default discipline for diagnosing a reported bug. The user's reproducible observation is ground truth — the analysis must explain it, not explain it away.

## Rules

1. **Observation over theory** — the user's reproducible facts are ground truth to explain; their causal explanation is only a hypothesis. Refuting the theory ≠ explaining the observation. (User imprecision usually lives in the explanation, not the observation.)
2. **Entry point over name** — statically trace the call graph from the actual UI/CLI entry point (the thing the user clicked/ran) down to the outcome. Never anchor on a function whose name merely matches the feature.
3. **The exercised path, not a correct path** — when ≥2 plausible code paths exist, verify the one actually hit. Proving a correct path exists is not proving the user's path is correct.
4. **Reproduce or it's unsolved** — analysis that cannot reproduce the user's concrete observation is INCOMPLETE. Never conclude "not a bug" until the observation is explained. A clash between analysis and a user-observed fact is a STOP signal, not a footnote. When the repro artifact is a test, it must be RED against the documented contract on the buggy revision, not green mirroring the defect — see `coding-best-practices` § Workflow Discipline TDD "Repro tests go RED first".

The classic failure violates all four at once: anchoring on the user's theory instead of the observation, tracing a function by name instead of from the button, proving that *a* correct path exists, and rationalizing a contradiction away instead of stopping.

This is a FORWARD trace (entry point → symptom); the BACKWARD direction (which callers a changed function breaks) is `grumpy-review`'s call-tree walk.
