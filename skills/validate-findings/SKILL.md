---
name: validate-findings
description: Coordinator-only LLM validation pass. Adds ai_assessment / ai_verdict / ai_verdict_confidence and re-estimates missing risk/impact/scope on a consolidated v3 report.
allowed-tools: Read, Edit, Bash(*validate_report.py *), Bash(git show *), Bash(git rev-parse *)
model: inherit
---

# Validate Findings

Opt-in coordinator-only step that runs an LLM validation pass over a consolidated v3 report. Adds AI assessment, verdict, and confidence to each finding, and fills in missing OWASP float dimensions when a producer omitted them. NOT part of the automatic review pipeline — invoke after `consolidate_reports.py assemble` when a triage-quality validation pass is wanted.

**Argument**: `$ARGUMENTS` — path to the consolidated `report.json` to validate. Edited in place.

## Inputs

- A consolidated v3 report on disk (output of `consolidate_reports.py assemble`).
- The producer commit, when `metadata.commit` is present, for best-effort source lookup via `git show`.

## Per-finding loop

For each finding that does not already carry `ai_verdict`:

1. **Read context** — pull `description`, `recommendation`, any `code_snippets` (when absent, work from `description` alone), and optionally `git show <metadata.commit>:<path>` for the file referenced by `location`. Skip the `git show` lookup silently when `metadata.commit` is absent (non-git directory) or the command fails.
2. **Validate** — judge whether the finding holds against the code. Produce:
   - `ai_assessment` (Markdown) — rationale: what was checked, what was found, what the verdict turns on.
   - `ai_verdict` — one of `valid`, `false_positive`, `needs_investigation`, `out_of_scope`, `duplicate`.
   - `ai_verdict_confidence` — float 0.0–1.0 reflecting how sure the LLM is. Renderers visually fade the chip background as confidence drops; honest low values are useful.
3. **Estimate missing floats** — when any of `risk` / `impact` / `scope` is absent, score them per the OWASP recipes in `severity` skill § "OWASP Risk Rating normalization". Only fill what the producer omitted; never overwrite an existing producer value.
4. **Re-derive integer severity** — after writing or accepting floats, recompute `overall_severity` and the integer `severity` band. Arithmetic stays in Python, never in the LLM. Reuse the coordinator's helpers:

   ```python
   # Import directly — no re-implementation:
   from consolidate_reports import _derive_overall, _derive_severity_int
   overall = _derive_overall(finding)
   if overall is not None:
       finding["overall_severity"] = overall
       finding["severity"] = _derive_severity_int(overall)
   ```

   If importing is impractical in the session, shell out to a one-liner that invokes the same helpers from `scripts/consolidate_reports.py`. Never recompute the band table inline.

Write changes back with the `Edit` tool — single JSON file, in place. No `Write` permission needed.

## Post-loop

1. **Re-validate** against the schema:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py "$ARGUMENTS"
   ```

   Fail loudly if validation fails — the AI updates must not break the report.
2. **Re-sort** `findings[].findings` by `overall_severity` desc (then by integer `severity` desc, then by `id` asc) so the highest-impact items surface first after re-estimation.

## Scope and boundaries

- Single-shot per invocation. No loops, no follow-ups — call again on a different file if needed.
- Producers and the coordinator stay unchanged. This skill only adds AI fields and float estimates that producers left empty.
- Never edit `metadata.repository`, `metadata.commit`, `location_permalink`, or `id`. Those are coordinator-owned.
- Never assign `ai_verdict_confidence = 1.0` as a default. When the LLM is uncertain, say so honestly — the renderers communicate that visually.
