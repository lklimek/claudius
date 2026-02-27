---
name: triage-findings
description: >
  Interactive triage of review findings. Starts a local server with a triage UI.
  User classifies findings in browser, decisions are written back to report.json.
  Use after grumpy-review to let the user decide what to fix, accept, or defer.
user-invocable: true
argument-hint: <path to report.json>
allowed-tools: Read, Write, Edit, Bash(python3 *), Bash(kill *), Glob, Grep
---

# Interactive Finding Triage

Start an interactive triage session for review findings. The user classifies each
finding in a browser UI, and decisions are written back to the report JSON.

**Argument**: `$ARGUMENTS` — path to the `report.json` file produced by `grumpy-review`.

## Workflow

1. Validate the report JSON against the schema:
   ```bash
   python3 scripts/validate_report.py "$ARGUMENTS"
   ```
   Requires `python3-jsonschema` (`apt install python3-jsonschema`).
   If validation fails, fix the JSON and re-validate before proceeding.
   Do NOT start the triage server with invalid data.

2. Start the triage server:
   ```bash
   python3 scripts/triage_server.py "$ARGUMENTS"
   ```
   The server auto-opens a browser. If that fails, it prints the URL for the user.

3. Wait for the user to complete triage in the browser and submit decisions. The
   server writes the `triage` field back into the report JSON and exits.

4. Read the updated report JSON. Summarize the triage results:
   - How many findings were triaged
   - Breakdown by action (fix, accept_risk, defer, false_positive, duplicate)
   - List all `fix` decisions with their finding IDs and titles

5. For findings marked `fix`: use the finding's `location`, `description`, and
   `recommendation` fields to apply the recommended fixes. Work through them
   one at a time, verifying each fix before proceeding to the next.

## Output

The report JSON file is updated in-place with a `triage` field containing all
decisions. This can be consumed by other tools or re-rendered with
`generate_review_report.py`.
