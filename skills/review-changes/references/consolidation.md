# Consolidate Findings

After all workers complete, scripts do the mechanical work; judgment calls remain coordinator-owned. Run through § Finalize even when every producer file is `[]`. Use the actual producer list (one in basic mode), without launching extra reviewers. Preserve caller-supplied Pass C files in the same consolidation. `<REPORT_DIR>` defaults to the current directory.

## Prepare

Flatten all agent reports, detect duplicate candidates, scan for INTENTIONAL comments (`<REPO_ROOT>` from `git rev-parse --show-toplevel`):

```bash
python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py prepare security:<SCRATCH_DIR>/security-findings.json project:<SCRATCH_DIR>/project-findings.json qa:<SCRATCH_DIR>/qa-findings.json --repo-root <REPO_ROOT> --base-ref <BASE_REF> --output <SCRATCH_DIR>/intermediate.json --digest --commit <COMMIT> --branch <BRANCH>
```

Label each producer file `<role>:<path>` with its role token (plus `lint:` and any caller-supplied files, such as Pass C); the label is the `<agent>` in every finding key below. Metadata goes in plain flags (`--commit`, `--branch`, `--project`, `--date`), never JSON on the command line; `project` defaults to the GitHub `owner/repo`, `date` to today (UTC), `--branch` is optional. Make prepare the first call after reviewers return, in the same message as `Skill(claudius:severity)` and a Read of `<MERGE_CLASSIFICATION>` (both needed in § Decide; skip either if this session already loaded it).

Writes `intermediate.json` (full `raw_findings`, `duplicate_groups`, `intentional_downgrades`, `section_positives`, `agent_stats`; `metadata.plugin_version` auto-filled) and prints `digest.md` — every finding's `<agent>:<original_id>` key, band, floats, location and clipped description, plus duplicate groups and INTENTIONAL hits by key. Decide from the digest (re-read `<SCRATCH_DIR>/digest.md` if the output was truncated); open `intermediate.json` only when a finding's full text matters.

## Decide (LLM judgment)

1. **Duplicate resolution**: per duplicate group, merge (keep the most detailed description, union tags) or keep separate.
2. **INTENTIONAL downgrade**: downgrade each INTENTIONAL hit to `INFO` (lower its floats) — deliberate engineering decisions from previous triage.
3. **Severity re-evaluation**: re-assess every finding strictly against `severity` — agents often over-inflate.
4. **Merge classification**: assign `merge_class` to EVERY finding per `severity` skill § Merge Classification and its `merge-classification.md` reference (decision tree) — `blocking` only when a blocker gate trips, with `intent_basis` naming the gate ID plus one line of evidence. Use the Context Digest when the invoker supplied one (`review-pr` § Context Digest) for `G-INTENT` judgment; with no PR context, derive intent from your own knowledge of the work's goal — the coordinator often knows the bigger picture the producers don't. Apply the digest as a coordinator-side backstop too: re-check any finding whose floats ignore an evidenced operational-profile claim a producer plainly didn't have (`severity` skill § `likelihood`). Severity never determines `merge_class`. Escalate to the human explicitly (never silently defer) any pre-existing finding tripping `G-FUNDS`/`G-SECRET`/`G-CRYPTO`/`G-DATA`.
5. **Executive summary**: write `overall_assessment`, `summary_text`, `verdict_text`, `verdict_action` consistent with merge classification and coverage. Include mode, completed passes, coverage status, limitations, and coverage-artifact paths. Zero findings with complete coverage permits a positive summary; unresolved paths require an incomplete verdict.

Record all of it in one Write of `<SCRATCH_DIR>/merge-decisions.json` — the only merge path; never hand-transcribe findings:

```json
{
  "executive_summary": { "overall_assessment": "...", "summary_text": "...", "verdict_text": "...", "verdict_action": "..." },
  "merges": [
    {
      "reason": "Both findings describe the same unchecked parser failure.",
      "members": [ { "agent": "security", "original_id": "SEC-001" }, { "agent": "qa", "original_id": "QA-003" } ],
      "base": { "agent": "security", "original_id": "SEC-001" },
      "updates": { "description": "Hand-authored merged text.", "tags": ["..."] }
    }
  ],
  "finding_updates": {
    "security:SEC-001": { "merge_class": "blocking", "intent_basis": "G-SECRET: token logged at src/auth.rs:88" },
    "project:PROJ-002": { "merge_class": "non_blocking", "likelihood": 0.2, "impact": 0.1 }
  }
}
```

- `merges`: true duplicate clusters only (omit candidates kept separate); `updates` carries the complete merged value of every combined field (e.g. the union of `tags`/`code_snippets`).
- `finding_updates`: keyed `<agent>:<original_id>`; only `merge_class`, `intent_basis`, `likelihood`, `impact`, `relevance`. Every surviving finding needs a `merge_class` (from here or from its producer); target a merged cluster's base, never a merged-away member.
- Optional `top_findings_override`/`remediation_override`: a JSON array replaces auto-generation.
- Optional `pr_comments` (`{"<agent>:<original_id>": "text" | null}`; a merged-away member's key targets its cluster base) and `pr_review_body` (string): finalize writes them as `<REPORT_DIR>/comments.json` keyed by final IDs and `<REPORT_DIR>/body.md` — `post_pr_review.py`'s `--comments`/`--body-file` inputs — so no one reads `report.json` for final IDs.

## Finalize

```bash
python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py finalize --input <SCRATCH_DIR>/intermediate.json --decisions <SCRATCH_DIR>/merge-decisions.json --output <REPORT_DIR>/report.json --format md
```

Applies the decisions (writing `<SCRATCH_DIR>/merged-findings.json` for audit), assigns sequential IDs by category, computes `summary_statistics`/`top_findings`/`remediation`, validates against the schema, and renders one file per `--format` (repeatable: `md`, `html`, `pdf`; default `md`) next to `report.json`. All-or-nothing: on failure no report, render, `comments.json`/`body.md` or `merged-findings.json` is written, and any left by an earlier run are renamed to `*.stale`; on success, renders of formats not requested this time are renamed `*.stale` too. Exit 1 names each finding lacking `merge_class`, each invalid decision (e.g. `blocking` without `intent_basis`), each schema error, or a failed render — fix `merge-decisions.json` (or the format) and re-run; exit 2 means an input file is missing or unparseable. After hand-editing `report.json`, re-validate with `validate_report.py <REPORT_DIR>/report.json`.

When presenting results, filter the consolidated findings for `merge_class == "out_of_scope_follow_up"` and name that list to the user as deferral candidates — nothing files them, so an unmentioned deferral is an invisible one (`claudius:severity` § `out_of_scope_follow_up`).

## Stop reviewer processes

Foreground `Agent` calls that have returned are finished — send them nothing. Only for reviewers spawned as persistent teammates (team/tmux-backed), after consolidation send `SendMessage({to: <name>, message: {type: "shutdown_request"}})` — the structured object, never a JSON string — to each, including ones already marked inactive (`grand-admiral` § Terminating Teammates), then sweep orphaned panes per `grand-admiral` § Orphaned Panes and Processes.
