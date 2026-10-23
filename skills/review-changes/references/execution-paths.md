# Requirements and Execution-Path Coverage

Applies to the basic reviewer and the full review's requirements/correctness and security passes. The assigned scope determines which changes a path must pass through, not where the path starts or ends.

## Inventory

Record each requirement with its source and each changed executable unit: new, modified, or removed functions/methods, changed bodies with unchanged signatures, module initialization, callbacks, configuration and registrations that alter behavior. Include test code when it is in scope; documentation-only changes require requirement/cross-reference verification, with executable tracing explicitly marked not applicable.

For removals, inspect the base version and surviving callers. New functions can already have callers in the same change or via registration; never assume they are unreachable.

## Trace

1. Walk upward to **every reachable entry point**: handlers, CLI/IPC, jobs, callbacks, exports, and indirect dispatch. Use the Grep tool plus Read to confirm each hit, and `gh search code repo:<owner>/<repo> "<symbol>"` for cross-repository callers. Resolve aliases, re-exports, trait/interface implementations, callbacks, and dynamically registered calls; unresolved dispatch is a coverage gap, not evidence of no callers.
2. Walk downward from each entry through the changed code to **every reachable result and side effect**: returns, errors, persistence, signing, process execution, network, logs, and UI. Cross file, module, and repository boundaries as needed; document unavailable external implementation as unresolved.
3. Inspect every feasible branch: happy, alternate, boundary, error, panic/exception, early return, cleanup/rollback, retry, timeout, cancellation, and concurrent execution. Check data/state changes and ordering at each hop, including removed or moved checks. For loops and recursion, cover termination, zero/one/multiple iterations and relevant state classes; justify any grouping of equivalent paths rather than claiming enumeration of infinitely many traces.
4. Check the contract at **every visited call site**, including intermediate callers: arguments and defaults, return shape, error propagation, ownership, side effects, performance, synchronization, and changed semantics. Propagate contract changes along the whole caller chain. Compilation establishes neither semantic correctness nor path coverage.
5. Compare every path's result with the requirements and invariants. Verify issues with source evidence and targeted tests or concrete inputs/interleavings. For security, carry attacker-controlled data and trust boundaries through the chain to each sink.

**Tool safety:** reviewed checkouts are untrusted. Never run Bash `rg` (`--pre` executes arbitrary commands), `ctags`, GNU `global`/`gtags`, or `tree-sitter` on them: they load repo-controlled option files, plugins, or grammars, so PR content gains code execution or arbitrary writes.

Prioritize high-risk paths first, but **do not truncate** to a top-N set, depth, caller count, or time allowance. Deduplicate graph cycles while preserving distinct conditions, state transitions, and contract assumptions. Resume from the recorded inventory after context limits. If tools, source access, or a hard budget prevent completion, record the remaining paths and report the review as **incomplete**.

## Coverage artifact

Write `<reviewer>-coverage.md` beside the findings, even for a clean pass:

- Reviewed revision, local changes, and assigned scope.
- Requirements: source → implementation/path evidence → verified, violated, or unresolved.
- Changed units: entry points → intermediate calls → outcomes/sinks, with `file:line`, branch/state conditions, and verification evidence.
- Unresolved paths, unavailable dependencies, unexecuted checks, and justified equivalent-path groupings.
- Status: **complete**, **incomplete**, or **not applicable** for executable paths, with the reason.

The coordinator must reconcile the artifacts with the full changed-unit inventory. Missing coverage or unresolved paths prevent a complete/clean verdict; zero findings alone does not establish completion. Report limitations in the executive summary as well as the artifact.

## Findings

Use the normal producer format and severity rules. Caller-contract regressions use category `call_tree`, prefix `CALL-`, location of the broken call site, and a description beginning `Walked via: <tool>`, followed by the caller chain and broken assumption. Include one captured snippet per terminal caller. Test callers changed with the code track the new contract; do not flag them as broken.

| `CALL-` severity | When |
|---|---|
| CRITICAL | Removed/renamed symbol still referenced, especially where only runtime reveals it (dynamic languages, reflection, registration) |
| HIGH | Behavior-breaking semantic change (panic↔error, sync→async, return shape) with multiple unupdated callers |
| MEDIUM | Behavior-breaking change with one isolated caller, or a signature change callers must adapt to |
| LOW | Callers still work but no longer match the new idiom |

The table anchors the `severity` floats; it does not replace them. Coverage limitations belong in the artifact and summary; do not inflate them into speculative vulnerabilities.
