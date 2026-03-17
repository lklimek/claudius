# Source of Truth — Knowledge Source Priority Map

## Knowledge Source Priority

| Knowledge Type | Primary Source | Store? |
|---|---|---|
| PR/issue status, reviews, comments | VCS / issue tracker API | NEVER |
| CI / build status, test results | Fresh build / CI API | NEVER |
| Dependency versions, file contents | Source files directly | NEVER |
| TODOs / deferred work | Task/todo system, issue tracker | NEVER |
| Architecture decisions & rationale | Persistent memory | ALWAYS |
| Coding standards & conventions | Persistent memory | ALWAYS |
| Design patterns adopted in project | Persistent memory | ALWAYS |
| Bad-thinking corrections | Persistent memory | ALWAYS |
| Tool / environment quirks | Persistent memory | ALWAYS |
| User preferences | Persistent memory | ALWAYS |
| Layer / module / file responsibilities | Persistent memory | ALWAYS |

## What to Store — Quality Gate

Every candidate memory must pass ALL criteria:

1. **Self-contained** — makes sense without conversation context
2. **Specific** — names the tool, library, pattern, or API
3. **Actionable** — future session can use it to avoid a mistake or make a decision
4. **Durable** — will matter in 30 days; won't be invalidated by next commit
5. **Not redundant** — not in source code, linter rules, or existing memories

## Search Priority

1. **Live source** (VCS API, CI, source code) — always freshest
2. **Persistent memory** — decisions, patterns, lessons not in code
3. **Indexed standards** — compliance, best practices, security guidelines

## Examples

**Good (store):**
- "dpp `document_type.validate_document()` returns `ConsensusValidationResult` not `Result<>` — check `.errors()` not `?`"
- "claudius worktree agents fork from `origin`, not local HEAD — unpushed commits are invisible"
- "Rust convention: typed errors via `thiserror`, never `String` — enables pattern matching"
- "LanceDB `compact_files()` requires write lock — concurrent compaction causes silent data loss"

**Bad (reject):**
- "All 79 tests pass" — ephemeral state
- "Project uses React 18" — already in package.json
- "Fixed typo in README" — no future value
- "PR #42 merged" — VCS history tracks this
- "Well-structured error handling" — vague, not actionable
- "severity_counts uses string label keys" — implementation detail in code

## Opportunistic Cleanup

When encountering existing memories that fail the quality gate:
- Vague / context-dependent → update to be self-contained and specific
- Ephemeral / obsolete → delete
- Near-duplicate of a better memory → delete the weaker one
