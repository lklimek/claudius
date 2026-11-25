# Consolidate Findings

After all workers complete, scripts do the mechanical work; judgment calls remain coordinator-owned. Run through § Finalize even when every producer file is `[]`. Use the assigned producer list. Preserve caller-supplied Pass C files in the same consolidation. `<REPORT_DIR>` is fixed in `review-changes` § 1.

## Prepare

Flatten all agent reports, detect duplicate candidates, scan for INTENTIONAL comments (`<REPO_ROOT>` from `git rev-parse --show-toplevel`):

```bash
python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py prepare security:<SCRATCH_DIR>/security-findings.json project:<SCRATCH_DIR>/project-findings.json qa:<SCRATCH_DIR>/qa-findings.json --repo-root <REPO_ROOT> --base-ref <BASE_REF> --output <SCRATCH_DIR>/intermediate.json --digest --commit <COMMIT> --branch <BRANCH>
```

Label each producer file `<role>:<path>` with its role token (plus `lint:` and any caller-supplied files, such as Pass C); the label is the `<agent>` in every finding key below. Metadata goes in plain flags (`--commit`, `--branch`, `--project`, `--date`), never JSON on the command line; `project` defaults to the GitHub `owner/repo`, `date` to today (UTC), `--branch` is optional. Make prepare the first call after reviewers return, in the same message as `Skill(claudius:severity)` and Reads of `<MERGE_CLASSIFICATION>` and `<SYSTEM_RATING>` (all needed in § Decide; skip any this session already loaded).

Writes `intermediate.json` (full `raw_findings`, `duplicate_groups`, `intentional_downgrades`, `section_positives`, `agent_stats`; `metadata.plugin_version` auto-filled) and prints `digest.md` — every finding's `<agent>:<original_id>` key, band, floats, location and clipped description, plus duplicate groups and INTENTIONAL hits by key. Decide from the digest (re-read `<SCRATCH_DIR>/digest.md` if the output was truncated); open `intermediate.json` only when a finding's full text matters.

## Decide (LLM judgment)

1. **Duplicate resolution**: per duplicate group, merge (keep the most detailed description, union tags) or keep separate. A slim-down drive-by finding and Pass C scope drift on the same hunk are duplicates; a merged cluster keeps the slim-down title delta (the smallest when members differ).
2. **INTENTIONAL and DECIDED downgrade**: downgrade each INTENTIONAL hit — deliberate engineering decisions from previous triage — and each DECIDED item (`<MERGE_CLASSIFICATION>` § Previously decided) to `INFO` by lowering its floats in `finding_updates` (e.g. `likelihood` and `impact` 0.0) and clearing any producer classification with `merge_class: null` (an INFO finding cannot stay `blocking`) — the band derives from the floats, so a relabel alone still demands a `merge_class`; list each DECIDED item once under "Previously decided" in `summary_text` with its decision reference.
3. **System-scale rating**: run the rating pass (`<SYSTEM_RATING>` § Rating pass) over every surviving finding — merged clusters by their base key, step 2's downgrades and `simplification` findings on the producer contract's slim-down rating excluded; producers rate from inside the diff and inflate component-local harm. Full mode: dispatch it to one fresh strong-model worker (`delegate`) given `intermediate.json`, the keys to rate (steps 1–2 applied) with each merged cluster's merged text, the project profile, anchors, calibration examples, and `<SYSTEM_RATING>`, returning `{key: {likelihood, impact, impact_description}}` for changed findings among those keys only; basic mode: run it yourself. Apply the result as `finding_updates`, except for a merged cluster: put its rated fields in the cluster's `updates`, which apply last and would otherwise overwrite them.
   Apply the LOW evidence rule in `severity` § Levels to all LOW ratings. Apply a rescore to LOW only when `impact_description` contains the required evidence.
4. **Merge classification**: assign `merge_class` to every non-INFO finding (INFO findings omit it) per `severity` skill § Merge Classification and its `merge-classification.md` reference (decision tree) — `blocking` only when a blocker gate trips, with `intent_basis` naming the gate ID plus one line of evidence. Use the Context Digest when the invoker supplied one (`review-pr` § Context Digest) for `G-INTENT` judgment; with no PR context, derive intent from your own knowledge of the work's goal — the coordinator often knows the bigger picture the producers don't. Apply the digest as a coordinator-side backstop too: re-check any finding whose floats ignore an evidenced operational-profile claim a producer plainly didn't have (`severity` skill § `likelihood`). Severity never determines `merge_class`; it only sets when `non_blocking` work is done (`severity` § 5). Escalate to the human explicitly (never silently defer) any pre-existing finding tripping `G-FUNDS`/`G-SECRET`/`G-CRYPTO`/`G-DATA`.
5. **Executive summary**: write `overall_assessment`, `summary_text`, `verdict_text`, `verdict_action` consistent with merge classification and coverage. Include mode, completed passes, coverage status, limitations, coverage-artifact paths, a `Slim-down: <K> findings, -<M> lines` line (when any) summing the title deltas of surviving `simplification` findings — each merged cluster once, INTENTIONAL, DECIDED and `disputed` ones excluded — and each artifact's *Considered, not filed* lines verbatim — information, never findings or fix items. When the `review-changes` § Two-provider gate applies, name its trigger and the providers that completed whole-PR coverage. A positive verdict requires complete coverage.

Record all of it in one Write of `<SCRATCH_DIR>/merge-decisions.json` — the only merge path; never hand-transcribe findings:

```json
{
  "executive_summary": {
    "overall_assessment": "...",
    "summary_text": "...",
    "verdict_text": "...",
    "verdict_action": "...",
    "review_coverage": {
      "complete": false,
      "required_reviewers": ["qa", "qa-agy"],
      "minimum_whole_pr_providers": 2,
      "completed_reviewers": {"qa": {"provider": "claude", "whole_pr": true}}
    }
  },
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

- `executive_summary.review_coverage`: list all required reviewer IDs, including unavailable reviewers. Add completed reviewers after verifying their coverage at the report's base and head. Use provider IDs `claude`, `codex`, or `agy`. Set `whole_pr: true` for an individual whole-PR pass and `whole_pr: false` for a specialist-only or partial pass. Set `minimum_whole_pr_providers` to 1 for ordinary PRs and 2 for the two-provider gate. Set `complete: false` for an incomplete verdict or missing coverage. `finalize` carries the evidence into `report.json` for the publisher.
- `merges`: true duplicate clusters only (omit candidates kept separate); `updates` carries the complete merged value of every combined field (e.g. the union of `tags`/`code_snippets`).
- `finding_updates`: keyed `<agent>:<original_id>`; only `merge_class`, `intent_basis`, `likelihood`, `impact`, `relevance`, `impact_description` (step 3's headline). Every surviving non-INFO finding needs a `merge_class` (from here or from its producer); target a merged cluster's base, never a merged-away member.
- Optional `top_findings_override`/`remediation_override`: a JSON array replaces auto-generation.
- Optional `pr_comments` (`{"<agent>:<original_id>": "text" | null}`; a merged-away member's key targets its cluster base) and `pr_review_body` (string): finalize writes them as `<REPORT_DIR>/comments.json` keyed by final IDs and `<REPORT_DIR>/body.md` — `post_pr_review.py`'s `--comments`/`--body-file` inputs — so no one reads `report.json` for final IDs.

## Finalize

```bash
python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py finalize --input <SCRATCH_DIR>/intermediate.json --decisions <SCRATCH_DIR>/merge-decisions.json --output <REPORT_DIR>/report.json --format md
```

Applies the decisions (writing `<SCRATCH_DIR>/merged-findings.json` for audit), assigns sequential IDs by category, computes `summary_statistics`/`top_findings`/`remediation`, validates against the schema, and renders one file per `--format` (repeatable: `md`, `html`, `pdf`; default `md`) next to `report.json`. All-or-nothing: on failure no report, render, `comments.json`/`body.md` or `merged-findings.json` is written, and any left by an earlier run are renamed to `*.stale`; on success, renders of formats not requested this time are renamed `*.stale` too. Exit 1 names each non-INFO finding lacking `merge_class`, each invalid decision (e.g. `blocking` without `intent_basis`), each schema error, or a failed render — fix `merge-decisions.json` (or the format) and re-run; exit 2 means an input file is missing or unparseable. After hand-editing `report.json`, re-validate with `validate_report.py <REPORT_DIR>/report.json`.

Then Write the run record `<REPORT_DIR>/review-run.json` from the values noted in `review-changes` § 1: `{"session_id", "base_sha", "head_sha", "reviewers": [{"role", "model", "started", "ended"}]}`, timestamps UTC ISO 8601, `"unknown"` for any value the host does not expose.

After each finalize, archive per `report-format` § File Output.

When presenting results, filter the consolidated findings for `merge_class == "out_of_scope_follow_up"` and name that list to the user, each with a proposed disposition — separate PR, issue, or drop (`claudius:severity` § 5). An unmentioned deferral is an invisible one.

## Stop reviewer processes

Foreground `Agent` calls that have returned are finished — send them nothing. Only for reviewers spawned as persistent teammates (team/tmux-backed), after consolidation send `SendMessage({to: <name>, message: {type: "shutdown_request"}})` — the structured object, never a JSON string — to each, including ones already marked inactive (`grand-admiral` § Terminating Teammates), then sweep orphaned panes per `grand-admiral` § Orphaned Panes and Processes.
