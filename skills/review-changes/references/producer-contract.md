# Producer Contract

Identical for every producer in a fan-out; spawn prompts point here (by absolute plugin path)
instead of restating it.

## Finding format (JSON)

Write findings to your assigned `<SCRATCH_DIR>/<role>-findings.json` as a bare JSON array of
`finding_section` objects — no envelope object, no metadata fields. Shape, required fields, the
do-NOT-emit list, and ID prefixes: explicitly load the `report-format` skill supplied by
the coordinator. Nicknames do not preload instructions.

- Rate `relevance` as real PR-goal fit — never default to `1.0`. Never hand-type a severity
  label; the floats are the single source of truth.
- `tags` are required for security findings: the OWASP Top 10:2025 category (`A01`–`A10`; A05 is
  Injection in 2025 — name the edition if you cite another) and the CWE.
- `cross_domain_hint` (optional): a peer role whose primary domain owns an issue you noticed
  incidentally — passively report it, never actively search outside your assigned scope.
- Assign provisional sequential IDs within your prefix (`SEC-001`, `SEC-002`) — collisions
  across parallel agents are fine, consolidation reassigns final IDs.

## Execution-path coverage

Read the shared execution-path contract at the absolute path in the brief. Apply the
assigned pass and write its coverage artifact, even when findings are empty. Requirements,
caller chains, and entry-to-sink paths follow that contract; report gaps explicitly.

## UI-text scan

For each new or changed user-visible string — labels, buttons, toasts, dialogs, error messages:

- **Truth**: a sentence that states, promises, or instructs is true in every state where it
  appears — show it in code — and every control it names exists and is reachable there.
- **Wording**: no raw exception text, stack traces, error codes, internal jargon, or alarming
  wording on a benign condition. These trip `G-UI-TEXT`.

## Always-flagged classes

Check all changed code, whatever the assigned focus: fixed secrets (keys, mnemonics, passwords,
tokens) in tests and fixtures; interactive widgets without an accessible name; raw error text
in logs and diagnostics.

## Slim-down

Run by the basic reviewer and, in full mode, by Adams; other producers skip it. Ask what the
diff can delete or merge while keeping its intent and test coverage: redundant fields, state or
collections; duplicated control flow within the diff; drive-by renames, reformatting or refactors
(`coding-best-practices` § Cross-Cutting Rules); tests asserting the same case twice. Duplication
of existing code stays under Adams' DRY. File each concrete change as a `code_quality` finding
tagged `simplification`, its title (under 150 characters, so the digest keeps it whole) ending
`(-<N> lines)`. Use the LOW evidence rule in `severity` § Levels before assigning
`likelihood` ≈ 0.3 and `impact` 0.1–0.3 by how much code a later change must read.
Rate a removable hunk that carries a defect as that defect.

## UX/DX lens

Assess how findings affect end-user workflows and developer experience, not just code
correctness.

## Collision preservation

Before writing your output file, check whether it already exists. If it is not your own
in-progress output, preserve it as `<role>-findings.PRE-COLLISION.json` before writing — never
silently overwrite another session's output.

## Bash hygiene

Restricted allowlists (e.g. CI) deny anything else, and each denial wastes a round: one
simple allowlisted command per call — no `$VAR`/`$(…)`, loops, pipes, `>` redirects, `cd`,
`git -C`, or `&&` chains; `python3 -c` and ad-hoc scripts are denied. Create files with the Write tool.
Prefer Read/Grep/Glob on the checked-out tree over `git show`/`cat`; read plugin files with
Read — Bash `ls`/`find` outside the working directory is sandbox-blocked.

## Process rules

- **Always write your output file, even when you found nothing.** A bare `[]` records
  a successful pass. A missing required output leaves the review incomplete.
- Run only the `consolidate_reports.py gate` command from your spawn prompt — never
  `prepare`/`finalize`, and do NOT pre-assemble `report.json` shape; the coordinator does that.
- When MemCan/WebSearch are unavailable (e.g., CI), do not use memcan tools or
  WebSearch/WebFetch.
- Load `coding-best-practices` and `severity` explicitly so their rules govern every finding.

## Report back tersely

Your findings file is the report. Write it, wait for the Write result, then run the `gate` command from your spawn prompt. If the Write failed, re-Write before running gate. On `INVALID:` or `ERROR:` fix the file (re-Write it whole if Edit is unavailable) and re-run gate. Then reply with your output file
path, your candy tally, and the `gate` output verbatim as the last lines (its `MAX:` line is
the coordinator's early-stop signal). Found nothing? `[]` gives `MAX: NONE` — a complete,
successful report. Do not restate findings in prose; the coordinator reads the JSON directly.
