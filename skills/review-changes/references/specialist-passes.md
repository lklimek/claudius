# Specialist Review Perspectives

Names identify the pass, not an installed agent type. Load the skills and coverage contract supplied by the coordinator.

## Adams — Global Optimum and Reuse

Judge whether the change solves the problem where it originates or settles for a local optimum. The frame is the whole project and the organization's sibling repositories (SDKs, shared libraries, services the code calls), not the diff.

- **Owning layer and repository**: trace each defect or need to the component that owns it. Flag consumer-side workarounds (UI, CLI, client) for a defect or gap in an organization-controlled dependency (SDK, library, service), and the reverse: generic logic placed in one consumer while others need it too.
- **Global design**: check whether existing upstream APIs, configuration, or extension points make the change unnecessary; whether it diverges from how the project and sibling repositories solve the same problem; whether it forces the same patch elsewhere.
- **DRY**: compare new code and new tests with each other and with existing helpers, utilities, fixtures, test builders, and test cases in the repository, its direct dependencies, and sibling repositories. Flag new tests that re-assert cases already covered elsewhere.
- **Cross-repository search** (within this pass's scope): use local checkouts, `gh search code --owner <org>`, and `gh api repos/<org>/<repo>/contents/<path>`. Treat MemCan `search_code` (project = repository name) as pointers only: it exposes no index date, so confirm every hit against the live default branch; when hits are missing or stale (index likely over a month old), record a re-index recommendation for the user in the coverage artifact.
- **Coverage artifact**: the layers and repositories checked per changed unit, those left unchecked (e.g. no `gh` or network in CI), and any re-index recommendation.

Support a source-level recommendation with the owning location, why the symptom originates there, and which other consumers benefit. State the cost of the global fix (cross-repository release, API change); "accept locally, file an upstream issue" is a valid recommendation. Label execution-dependent concerns for Marvin to verify.

Use `project` / `PROJ-` for global-optimum findings and `code_quality` / `CODE-` or language prefixes for duplication. Report findings only; never edit production code.

## Marvin — Requirements, Correctness, and Consistency

Apply the `review-changes` Reviewer pass to the entire assigned scope, including its requirements and execution-path coverage contract. Independently verify claims against the actual reviewed tree, not reports or commit messages.

Audit tests for contract coverage and assertion depth: computed values, exact boundaries, specific errors, side effects, ordering, and state consistency. Tests must assert intended behavior rather than mirror implementation; reject `assert result is not None`, `status == 200` without the body, `len(items) > 0` without which items, and "runs without error" without asserting output. Never change expectations to make buggy behavior pass.

For suspected races, provide a concrete interleaving or reproducing stress test. Spend verification on untested scopes and feature combinations; reuse valid current-tree ledger evidence, but distrust implausible records (`grand-admiral` § Verification Economy). Web UI projects need a smoke test of critical flows (page loads, forms submit, navigation, error states) with `playwright-cli`; probe `command -v playwright-cli || npx @playwright/cli@latest --version`. If unavailable, skip it and file a LOW finding rather than testing manually. Note incidental security concerns as a `cross_domain_hint`.

Also check code, configuration, docs, and tests for consistency: API contracts, config defaults, schemas/migrations, generated clients, test descriptions, and public documentation. Inspect naming, readability, idioms, maintainability, and needless abstractions; check that new public seams have test references. Read touched comments and docs against the coding rules; report mismatches with both source locations.

- **Dependencies**: versions consistent across packages; no redundant or unused deps; lock files present and current; new deps maintained and justified against existing packages. Semver ranges are fine where lock files exist (`Cargo.lock`, `go.sum`, `package-lock.json`, `poetry.lock`) — flag only missing or stale lock files.
- **Git**: clear, atomic commits; branch current with base; no accidental files (`.env`, IDE configs, build output).

Use `code_quality` / `QA-` for correctness findings, `project` / `PROJ-` for cross-artifact inconsistencies, `code_quality` / `CODE-` or language prefixes for structural issues, and `call_tree` / `CALL-` for caller regressions. Cite the requirement and command, breaking input, or traced path. Report findings only; fixes belong to the implementer.
