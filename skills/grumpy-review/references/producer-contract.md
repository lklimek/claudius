# Producer Contract Template

Copy this file to `<SCRATCH_DIR>/producer-contract.md` once per review (substitute nothing —
it's identical across producers). Every spawn prompt then points here instead of restating
these items. See `grumpy-review` § Craft Agent Prompts for the numbered source items this
mirrors, kept in sync with it.

## Finding format (JSON)

Write findings to your assigned `<SCRATCH_DIR>/<role>-findings.json` as a bare JSON array of
`finding_section` objects — no envelope object, no metadata fields:

```json
[
  {
    "title": "Section Title",
    "category": "security|project|code_quality|dependencies|documentation|call_tree",
    "findings": [
      {
        "id": "PREFIX-001",
        "likelihood": 0.6,
        "impact": 0.7,
        "relevance": 0.5,
        "title": "Short finding title",
        "tags": ["A03 Injection", "CWE-79"],
        "location": "src/auth.rs:42-56",
        "description": "What the issue is and why it matters",
        "impact_description": "What could go wrong (Markdown narrative)",
        "recommendation": "How to fix it",
        "code_snippets": [
          {"language": "rust", "caption": "auth.rs:42", "content": "let user = unwrap_token(&hdr);"}
        ]
      }
    ],
    "positives": "Optional positive observations"
  }
]
```

**Required per finding**: `id`, `likelihood`/`impact`/`relevance` (floats 0.0–1.0), `title`,
`location` (full file path, e.g. `src/auth.rs:42-56` — never a bare line number),
`description`, `recommendation`. Rate `relevance` as real PR-goal fit — never default to
`1.0`. The floats are the single source of truth; never hand-type a severity label.

**Optional**: `tags` (OWASP `A01`–`A10`, CWE, language best-practice IDs — required for
security findings), `impact_description`, `code_snippets` (only from source you actually
captured — never invent one), `cross_domain_hint` (a peer role whose primary domain owns an
issue you noticed incidentally — passively report it, never actively search outside your
assigned scope).

**Do NOT emit** (downstream-owned): `overall_severity`, `location_permalink`, any
`metadata`/`commit`/`repository`/`date`/`branch` field, `ai_assessment`, `ai_verdict`,
`ai_verdict_confidence`, `merge_class`, `intent_basis`, the derived integer `severity` when
emitting floats. Missing any of `likelihood`/`impact`/`relevance` fails schema validation.

**ID prefixes**: `SEC-` security, `PROJ-` project, `QA-`/`CODE-`/`RUST-`/`PY-`/`GO-`/`FE-`
code quality, `DOC-` docs, `CALL-` call-tree. Assign provisional sequential IDs within your
prefix (e.g. `SEC-001`, `SEC-002`) — collisions across parallel agents are fine, consolidation
reassigns final IDs.

## Call-tree inspection

When the diff modifies or removes any function/method declaration, run a deep transitive
in-repo caller walk before emitting findings — see `references/call-tree-walk.md` (read once
per review). Finding shape: `category: "call_tree"`, ID prefix `CALL-`, `description` MUST
start with `Walked via: <tool>`. Skip for pure additions, doc-only PRs, and test-file-only
changes.

## UI-text scan

Scan the diff's user-visible strings — labels, buttons, toasts, dialogs, error messages — for
raw exception text, stack traces, error codes, internal jargon, or alarming wording on a
benign condition. These trip `G-UI-TEXT`.

## UX/DX lens

Assess how findings affect end-user workflows and developer experience, not just code
correctness.

## Collision preservation

Before writing your output file, check whether it already exists. If it is not your own
in-progress output, preserve it as `<role>-findings.PRE-COLLISION.json` before writing — never
silently overwrite another session's output.

## Process rules

- Do NOT run `consolidate_reports.py` yourself and do NOT pre-assemble `report.json` shape —
  the coordinator does that.
- Use the Write tool for creating files — never `cat > file` or heredoc redirections.
- When MemCan/WebSearch are unavailable (e.g., CI), do not use memcan tools or
  WebSearch/WebFetch.
- Preload `coding-best-practices` so its Cross-Cutting Rules govern every finding.

## Report back tersely

Your findings file is the report — the coordinator reads it directly. When you finish, report
back in **at most 3 lines**: counts by severity band, your output file path, and your candy
tally. Do not restate your findings in prose; a 1-2 KB narrative repeating the JSON you just
wrote wastes tokens the coordinator has to read anyway.
