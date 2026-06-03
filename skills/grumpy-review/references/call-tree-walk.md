# Call-Tree Walk Methodology

Authoritative recipe for deep transitive in-repo caller analysis on a PR. Referenced by `grumpy-review`, `review-pr`, and `check-pr-comments` skills.

## Outcome

For every function modified by the diff, surface every transitive in-repo caller whose assumption-set is invalidated by the new contract. Findings name the caller's `file:line`, the assumption that was broken, and the chain back to the modified function.

## When to Run

Trigger only when `git diff $BASE_BRANCH...HEAD` shows modified or removed function/method declarations. Skip for:

- Pure additions (new functions, no callers exist yet).
- Doc-only PRs.
- Comment-only or whitespace-only diffs.
- Changes confined to test files (callers are tests; the walk is noise).

A signature change without a body change still triggers — callers may depend on the old signature.

## Step 1 — Inventory Modified Functions

Enumerate every modified/removed function or method declaration from the diff. For each entry record:

- Fully qualified name (`module::path::function` for Rust, `package.Type.method` for Go, `pkg.module.func` for Python, `Class#method` for JS/TS).
- Language.
- Visibility: `public` / `private` / `trait-or-interface-impl` / `leaf`.
- Change shape: `signature-changed` / `body-only`.
- Source location (`path:line`).

Drop pure additions — they have no in-repo callers yet.

## Step 2 — Rank and Truncate

Score each entry on these dimensions (higher = more risk):

| Dimension | High risk | Low risk |
|---|---|---|
| Visibility | public, trait/interface impl | private, leaf |
| Change shape | signature-changed | body-only |
| Module reach | widely-imported module, core trait | local utility, test helper |

Order descending by composite risk. Keep the **top 10** and walk those. Defer the rest.

Emit one INFO finding listing every modified function, marking which were walked vs deferred and why:

```text
category: "call_tree"
id: CALL-NNN (coordinator-assigned)
risk: 0.1
impact: 0.1
scope: 0.3
title: "Call-tree walk scoped to top 10 of N modified functions"
description: |
  Walked via: <tool>
  Walked: foo::bar, foo::baz, ...
  Deferred (lower risk): foo::leaf_util, ...
```

## Step 3 — Probe Tooling

Discover what the environment offers. Run cheap `which` probes once, cache the answers — `which` is the only detection primitive on every skill's allow-list, so prefer it over `test -f`/`ps -e` (which the sandbox blocks):

```bash
which ctags global gtags rg ripgrep tree-sitter 2>/dev/null
```

The probe order is tool-agnostic — pick whatever the environment actually offers. Suggested order:

| Tier | Tool | When |
|---|---|---|
| Best | `ctags -R --languages=<lang>` (universal-ctags) | Language-aware, fast, scriptable |
| Best | GNU global (`gtags` + `global -r <sym>`) | Language-aware, fastest cross-ref |
| Good | `tree-sitter query` | When grammar is installed; precise AST queries |
| OK | `gh search code repo:<owner>/<repo> "<symbol>"` | Cross-repo same-org (limited rate) |
| Fallback | `rg -n --type <lang> '<caller-regex>'` | Always available |

Record which tool you used; every emitted `CALL-` finding must include `Walked via: <tool>` (e.g. `Walked via: ctags + rg fallback`).

### Fallback regex hints

| Language | Caller-extraction regex |
|---|---|
| Rust | `\b(<fn>|<Type>::<fn>)\s*\(` plus `use .*::<fn>` for re-exports |
| Python | `\b<fn>\s*\(` plus `from .* import <fn>` and `self\.<fn>\s*\(` |
| Go | `\b<fn>\s*\(` plus `\.<fn>\s*\(` for receiver methods |
| JS/TS | `\b<fn>\s*\(` plus `import.*\b<fn>\b` and `\.<fn>\s*\(` |

## Step 4 — Walk

BFS from each modified function. Track the caller chain via parent pointer.

Caps (per function):

- **Depth**: 5 hops.
- **Caller count**: 200 unique callers.
- **Wall-clock**: 60 seconds.

Dedupe by `file:line`. When any cap trips, stop that walk and emit one `CALL-` INFO finding noting the truncation point and which cap fired:

```text
title: "Call-tree walk truncated at depth 5 for foo::bar"
description: |
  Walked via: <tool>
  Stopped at depth 5 with 87 callers enumerated; further hops not explored.
```

Skip walks that visit only test files — record as deferred in the ranking finding.

## Step 5 — Per-Caller Judgement

For each terminal caller, re-read the caller's code around `file:line` and check whether the assumption-set still holds. Mismatches become `CALL-` findings.

Assumptions to verify (per the modified function's new contract):

1. **Signature**: argument types, count, defaults, generic bounds.
2. **Return shape**: type, `Option`/`Result` wrapping, ownership.
3. **Error contract**: error variant added/removed; `?` propagation still typechecks; previously infallible call now fallible.
4. **Panic vs Result**: previously panicked, now returns `Err` (or vice versa).
5. **Side effects**: added I/O, lock acquisition, allocation, log emission.
6. **Performance**: previously O(1) now O(n); previously non-blocking now blocking.
7. **Concurrency**: thread-safety, `Send`/`Sync`, async-ness change.
8. **Semantics**: same arguments now produce different output (e.g. retry policy changed, default value changed).

For each broken assumption, emit a `CALL-` finding scoped to the caller's `file:line`. The chain back to the modified function goes in `description`.

### Severity rubric (composes with `claudius:severity`)

| Severity | When |
|---|---|
| CRITICAL | Removed/renamed symbol still referenced by callers — especially in dynamic languages where the bug surfaces at runtime, not at compile time |
| HIGH | Behaviour-breaking semantic change (panic→Result, sync→async, return-shape change) with multiple unupdated callers |
| MEDIUM | Behaviour-breaking change with a single isolated caller, or signature change callers must adapt to |
| LOW | Stylistic drift — callers still work but no longer match the new idiom |
| INFO | Ranking summary, truncation notes, deferred-walk notes |

Score `risk`/`impact`/`scope` per `claudius:severity`; let the coordinator derive the integer.

## Step 6 — Emit Findings

Finding shape (one section per modified function whose walk surfaced callers, or one consolidated section for the whole PR — pick whichever is more readable):

```json
{
  "title": "Call-Tree Inspection",
  "category": "call_tree",
  "findings": [
    {
      "id": "CALL-001",
      "risk": 0.6,
      "impact": 0.5,
      "scope": 0.5,
      "title": "Caller foo::bar still treats baz() as infallible",
      "location": "src/foo/bar.rs:142",
      "description": "Walked via: ctags + rg fallback\nChain: src/foo/bar.rs:142 → baz() (modified at src/baz.rs:88)\nbaz() now returns Result<T, E>; caller uses the value directly without `?` or matching on Err.",
      "recommendation": "Propagate the error via `?` or handle Err explicitly.",
      "code_snippets": [
        {"language": "rust", "caption": "src/foo/bar.rs:140-145", "content": "let x = baz();\nuse_x(x);"}
      ]
    }
  ]
}
```

Required fields on every `call_tree` finding:

- `category: "call_tree"`.
- `id`: `CALL-NNN` — the producer emits a provisional ID; the coordinator reassigns.
- `description`: MUST include a line `Walked via: <tool>` and the chain `<caller> → … → <modified-function>`.
- `code_snippets`: one snippet per terminal caller with `language` matching the repo.
- `location`: caller's `file:line` (not the modified function's location — the finding is about the caller).

Optional but encouraged: `tags` such as `signature-change`, `return-shape`, `panic-to-result`.

## Anti-Patterns

- **Walking every modified function on a 200-file refactor**. Rank, truncate to top 10, surface the rest as deferred.
- **Treating compile-time-checked callers as automatically safe**. Rust/TS will catch shape mismatches at the type level, but semantic changes (retry policy, default value, panic→Result re-wrap) still slip through — read the caller.
- **Walking into test files and flagging them as broken**. Tests track the new contract by definition; treat them as expected callers and skip emission.
- **Skipping the `Walked via:` line**. Without it the reader can't judge how thorough the walk was.
