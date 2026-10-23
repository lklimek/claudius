# QA Authoring

Spec-matching QA: prove the code does not meet its requirements, then leave tests in the repository that keep it honest. Work in the assigned worktree; never fix production code — non-conforming code is a finding for the implementer.

1. **Requirements first.** Build the expected-behavior model before reading code or tests. Precedence: acceptance criteria > API/architecture docs > code docs/README > UX/DX conventions. "Working as implemented" is no defense; misleading or incomplete docs are bugs too.
2. **Audit existing tests** for coverage, assertion depth, edge cases, error paths, and boundaries, per sibling `specialist-passes.md` § Marvin. Flag every gap.
3. **Write missing tests** that fail when a requirement is unmet. Follow the project's test layout and conventions. Never adjust a test to match buggy code; change expectations only when requirements change.
4. **Execute all tests** through the project's verification tooling and analyze every failure. Diagnose failures with `bug-investigation`.
5. **Report** every requirement-vs-behavior mismatch per `report-format` (`QA-`, `code_quality`), with the requirement reference, expected vs actual, and the failing test or command as evidence. List the tests added.

## Manual test scenarios

On request, write `docs/manual_tests/manual_test_<feature>.md`: preconditions, numbered steps, the expected result per step, and edge cases — reproducible by someone unfamiliar with the code.
