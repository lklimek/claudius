# Source of Truth — Knowledge Source Priority Map

Where to find information, where to store it, and what never to save.

## Knowledge Source Priority

| Knowledge Type | Primary Source | Fallback | Store in persistent memory? |
|---|---|---|---|
| PR status, reviews, comments | Issue tracker / VCS hosting API | — | NEVER — live authoritative source |
| Issue status, labels, assignments | Issue tracker API | — | NEVER — live authoritative source |
| CI / build status | Fresh build / CI API | — | NEVER — live authoritative source |
| Dependency versions | Source files (Cargo.toml, package.json, etc.) | — | NEVER — already in code |
| Test results | Fresh test run | — | NEVER — ephemeral state |
| File contents / current code | Direct file read / code search | — | NEVER — already in code |
| TODOs / deferred work | Dedicated task/todo system | Issue tracker | NEVER — tracked elsewhere |
| Architecture decisions & rationale | Persistent memory | Source code comments | ALWAYS |
| Coding standards & conventions | Persistent memory | Linter configs, style guides | ALWAYS |
| Design patterns adopted in project | Persistent memory | Source code examples | ALWAYS |
| Bad-thinking corrections | Persistent memory | — | ALWAYS |
| Tool / environment quirks | Persistent memory | — | ALWAYS |
| User preferences | Persistent memory | — | ALWAYS |
| Layer / module responsibilities | Persistent memory | Source code structure | ALWAYS |
| File responsibilities | Persistent memory | Source code structure | ALWAYS |

## What to Store — Quality Gate

Every candidate memory must pass ALL criteria:

1. **Self-contained** — makes sense without conversation context
2. **Specific** — names the tool, library, pattern, or API
3. **Actionable** — future session can use it to avoid a mistake or make a decision
4. **Durable** — won't be invalidated by next commit/deploy; will matter in 30 days
5. **Not redundant** — not already captured in source code, linter rules, or existing memories

## What to Search — Priority Order

1. **Live authoritative source** (VCS API, CI, source code) — always freshest
2. **Persistent memory** — decisions, patterns, lessons not captured in code
3. **Indexed standards** — compliance, best practices, security guidelines

## Never Store (Noise)

- Ephemeral state — "tests pass", "build succeeded", "PR merged"
- Process notes — "created file X", "commit abc123"
- Facts already in source code — dependency versions, config values
- Vague observations — "good structure", "well-organized"
- Activity logs — only save the LESSON, not a description of what was done

## Good vs Bad Memory Examples

**Good (store these):**
- "Dash Platform dpp: `document_type.validate_document()` returns `ConsensusValidationResult` not `Result<>` — must check `.errors()` not use `?` operator"
- "claudius worktree agents: fork from `origin`, not local HEAD — unpushed local commits are invisible to worktree agents"
- "Rust error handling convention: return typed errors via `thiserror`, never `String` — enables pattern matching and proper error propagation"
- "LanceDB compact_files() requires write lock — concurrent compaction causes silent data loss"

**Bad (reject these):**
- "All 79 tests pass" — ephemeral status
- "Project uses React 18" — already in package.json
- "Fixed typo in README" — no future value
- "PR #42 merged" — VCS history
- "Well-structured error handling" — vague praise
- "severity_counts uses string label keys" — implementation detail in source code

## Opportunistic Cleanup

When searching and encountering existing memories that fail the quality gate:
- Vague / context-dependent -> update to be self-contained and specific
- Ephemeral / obsolete -> delete
- Near-duplicate of a better memory -> delete the weaker one
