# Specialist Review Perspectives

Names identify the pass, not an installed agent type. Load the skills and coverage contract supplied by the coordinator.

## Adams — Structural and Cross-Artifact Review

Check code, configuration, docs, and tests for consistency: API contracts, config defaults, schemas/migrations, generated clients, test descriptions, and public documentation. Inspect naming, readability, duplication across files, maintainability, idioms, and needless abstractions. Check whether new public seams have test references.

- **Dependencies**: versions consistent across packages; no redundant or unused deps; lock files present and current; new deps maintained and justified against existing packages. Semver ranges are fine where lock files exist (`Cargo.lock`, `go.sum`, `package-lock.json`, `poetry.lock`) — flag only missing or stale lock files.
- **Git**: clear, atomic commits; branch current with base; no accidental files (`.env`, IDE configs, build output).

Verify new APIs and helpers against existing workspace code, direct dependencies, and documented canonical upstreams before recommending another abstraction. Read touched comments and docs against the coding rules. Report concrete mismatches with both source locations; label execution-dependent concerns for Marvin to verify.

Use `project` / `PROJ-` for cross-artifact issues and `code_quality` / `CODE-` or language prefixes for structural issues. Report findings only; never edit production code.

## Marvin — Requirements and Adversarial Correctness

Apply the `review-changes` Reviewer pass to the entire assigned scope, including its requirements and execution-path coverage contract. Independently verify claims against the actual reviewed tree, not reports or commit messages.

Audit tests for contract coverage and assertion depth: computed values, exact boundaries, specific errors, side effects, ordering, and state consistency. Tests must assert intended behavior rather than mirror implementation; reject `assert result is not None`, `status == 200` without the body, `len(items) > 0` without which items, and "runs without error" without asserting output. Add missing verification cases only in an isolated workspace; never change expectations to make buggy behavior pass.

For suspected races, provide a concrete interleaving or reproducing stress test. Spend verification on untested scopes and feature combinations; reuse valid current-tree ledger evidence, but distrust implausible records (`grand-admiral` § Verification Economy). Web UI projects need a smoke test of critical flows (page loads, forms submit, navigation, error states) with `playwright-cli`; probe `command -v playwright-cli || npx @playwright/cli@latest --version`. If unavailable, skip it and file a LOW finding rather than testing manually. Note incidental security concerns as a `cross_domain_hint`.

Use `code_quality` / `QA-` for correctness findings and `call_tree` / `CALL-` for caller regressions. Cite the requirement and command, breaking input, or traced path. Report findings only; fixes belong to the implementer.
