# Producer Contract

Identical for every producer in a fan-out; spawn prompts point here (by absolute plugin path)
instead of restating it. Mirrors `grumpy-review` § Craft Agent Prompts — keep in sync.

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

## Bash hygiene

Restricted allowlists (e.g. CI) deny anything else, and each denial wastes a round: one
simple allowlisted command per call — no `$VAR`/`$(…)`, loops, pipes, `>` redirects, `cd`, or
`&&` chains; `python3 -c` and ad-hoc scripts are denied. Create files with the Write tool.
Prefer Read/Grep/Glob on the checked-out tree over `git show`/`cat`.

## Process rules

- **Always write your output file, even when you found nothing.** A bare `[]` is a valid,
  successful result — a missing file fails the coordinator's `prepare` step outright (exit 2),
  taking down the whole review with no report at all. Zero findings is never a reason to skip
  the Write call.
- Run only the `consolidate_reports.py gate` command from your spawn prompt — never
  `prepare`/`finalize`, and do NOT pre-assemble `report.json` shape; the coordinator does that.
- When MemCan/WebSearch are unavailable (e.g., CI), do not use memcan tools or
  WebSearch/WebFetch.
- Preload `coding-best-practices` so its Cross-Cutting Rules govern every finding.

## Report back tersely

Your findings file is the report. After writing it, run the `gate` command from your spawn
prompt; on `INVALID:` or `ERROR:` fix the file and re-run. Then reply with your output file
path, your candy tally, and the `gate` output verbatim as the last lines (its `MAX:` line is
the coordinator's early-stop signal). Found nothing? `[]` gives `MAX: NONE` — a complete,
successful report. Do not restate findings in prose; the coordinator reads the JSON directly.
