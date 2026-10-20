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
5. **Locate ownership before fixing** — identify the component responsible for the violated contract; apply [coding-best-practices](../coding-best-practices/SKILL.md) § Cross-Cutting Rules for architectural placement and local style. Distinguish a dependency defect from incorrect use of its API.
6. **Dependency defects require a user decision** — if the cause is in a dependency (including same-owner repositories, vendored code, or git-pinned dependencies), present the evidence, owning repository/version, and viable options, then ask the user what to do. Do not implement a caller-side workaround, patch the dependency, or change its version/source before that decision. A general request to fix the issue is not that decision. Delegated workers report this gate to the coordinator, who asks the user; continue only independent diagnosis while waiting.

The classic failure violates the first four rules at once: anchoring on the user's theory instead of the observation, tracing a function by name instead of from the button, proving that *a* correct path exists, and rationalizing a contradiction away instead of stopping.

This traces the exercised path from entry point to symptom. Review additionally checks all affected callers and outcomes through the shared coverage contract in [review](../review/SKILL.md).
