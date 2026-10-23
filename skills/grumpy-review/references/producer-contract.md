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
simple allowlisted command per call — no `$VAR`/`$(…)`, loops, pipes, `>` redirects, `cd`,
`git -C`, or `&&` chains; `python3 -c` and ad-hoc scripts are denied. Create files with the Write tool.
Prefer Read/Grep/Glob on the checked-out tree over `git show`/`cat`; read plugin files with
Read — Bash `ls`/`find` outside the working directory is sandbox-blocked.

## Process rules

- **Always write your output file, even when you found nothing.** A bare `[]` is a valid,
  successful result — a missing file fails the coordinator's `prepare` step outright (exit 2),
  taking down the whole review with no report at all. Zero findings is never a reason to skip
  the Write call.
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
