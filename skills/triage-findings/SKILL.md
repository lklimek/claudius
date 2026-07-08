---
name: triage-findings
description: Use for interactive browser-based triage of review findings. Only invoke when explicitly requested.
user-invocable: true
argument-hint: path/to/report.json
allowed-tools: Read, Write, Edit, Bash(*validate_report.py *), Bash(*triage_server.py *), Bash(fuser -k */tcp), Glob, Grep
---

# Interactive Finding Triage

Start an interactive triage session for review findings. The user classifies each
finding in a browser UI, and decisions are written back to the report JSON.

**Argument**: `$ARGUMENTS` — path to the `report.json` file produced by `grumpy-review` or `check-pr-comments`.

## Workflow

1. Validate the report JSON against the schema:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py "$ARGUMENTS"
   ```
   Requires `python3-jsonschema` (`apt install python3-jsonschema`).
   If validation fails, fix the JSON and re-validate before proceeding.
   Do NOT start the triage server with invalid data.
   The validator also prints non-blocking `[consistency]` warnings to stderr
   (label/band drift, or an un-rated axis such as `scope` pinned at `1.0`).
   These don't fail validation, but surface them to the user — severity labels
   are *derived* from `risk`/`impact`/`scope` per `claudius:severity`, never
   hand-typed, so a warning means the floats need rerating, not a label edit.

2. Start the triage server (default port 8741):
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../../scripts/triage_server.py "$ARGUMENTS" [--port PORT]
   ```
   The server auto-opens a browser. If that fails, it prints the URL for the user.

3. Wait for the user to complete triage in the browser and submit decisions. The
   server writes the `triage` field back into the report JSON and exits.

### Killing a stuck server

The server normally shuts itself down when the user submits with `complete=true`.
If it gets stuck, kill it by port — **never use `pkill -f`** (risks killing
servers from other sessions):

```bash
fuser -k 8741/tcp    # kills whatever is bound to port 8741
```

Replace `8741` with the actual port if `--port` was used.

4. Read the updated report JSON. Summarize the triage results:
   - How many findings were triaged
   - Breakdown by action (fix, accept_risk, defer, false_positive, duplicate)
   - List all `fix` decisions with their finding IDs and titles

5. For findings marked `fix`: use the finding's `location`, `description`, and
   `recommendation` fields to apply the recommended fixes. Work through them one at a time,
   verifying each achieves the desired end-user or developer experience (not just code
   correctness) before proceeding to the next.

6. For findings marked `defer`: add a `TODO` comment at the finding's location
   referencing the finding ID and title:
   ```
   // TODO(SEC-004): BannerHandle is Send+Sync but read-modify-write is not atomic
   ```
   Use the file's native comment syntax (`//`, `#`, `<!-- -->`, etc.).

7. For findings marked `accept_risk`: add an `INTENTIONAL` comment at the
   finding's location documenting the accepted risk and rationale:
   ```
   // INTENTIONAL(SEC-005): Relaxed ordering adequate for single-threaded UI model
   ```
   Include the rationale from the triage decision if provided, otherwise
   summarize from the finding's description. Future reviews that encounter
   an `INTENTIONAL` comment will downgrade the finding to INFO severity.

## Comment-Check Reports

For reports with `metadata.report_type == "comment_check"` (produced by `check-pr-comments`):

- Triage actions apply to unresolved PR review comments instead of code review findings
- **accept_risk / false_positive**: after triage, resolve the associated GitHub review
  thread using `${CLAUDE_SKILL_DIR}/../../scripts/gh-resolve-review-threads.sh` with the finding's `thread_id` field.
  Always ask user confirmation before resolving threads.
- **fix**: apply the fix described in `recommendation`, then resolve the thread
- **defer**: leave the thread unresolved; add a `TODO` comment as usual
- The triage decision's `resolve_thread` field (boolean) indicates whether thread
  resolution is appropriate for each decision

## Output

The report JSON file is updated in-place with a `triage` field containing all
decisions. This can be consumed by other tools or re-rendered with
`generate_review_report.py`.
