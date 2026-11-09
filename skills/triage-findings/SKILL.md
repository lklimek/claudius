---
name: triage-findings
description: "This skill should be used when the user explicitly asks to \"triage findings\" through an interactive browser-based workflow. Only invoke when explicitly requested."
user-invocable: true
argument-hint: path/to/report.json
allowed-tools: Read, Write, Edit, Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/triage_server.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(ghsudo ${CLAUDE_PLUGIN_ROOT}/scripts/gh-resolve-review-threads.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/gh-post-review-reply.sh *), Bash(fuser -k */tcp), Glob, Grep
---

# Interactive Finding Triage

Start an interactive triage session: the user classifies each finding in a browser UI, and decisions are written back to the report JSON.

**Argument**: `$ARGUMENTS` — path to the `report.json` produced by `review-changes` or `check-pr-comments`.

## Workflow

1. Validate the report JSON against the schema:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py "$ARGUMENTS"
   ```
   Requires `python3-jsonschema`. Invalid → fix and re-validate; never start the server with invalid data. Non-blocking `[consistency]` warnings on stderr (label/band drift, `relevance` pinned at `1.0`) don't fail validation but must be surfaced to the user — labels derive from the floats (`claudius:severity`), so a warning means the floats need rerating.

2. Start the triage server (default port 8741):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/triage_server.py "$ARGUMENTS" [--port PORT]
   ```
   The server auto-opens a browser; if that fails, it prints the URL for the user.

3. Wait for the user to complete triage in the browser and submit. The server writes the `triage` field back into the report JSON and exits.

### Killing a stuck server

The server normally shuts down when the user submits with `complete=true`. If stuck, kill it by port — **never `pkill -f`** (risks killing servers from other sessions):

```bash
fuser -k 8741/tcp    # kills whatever is bound to port 8741
```

Replace `8741` with the actual port if `--port` was used.

4. Read the updated report JSON and summarize the triage results:
   - How many findings were triaged
   - Breakdown by action (fix, accept_risk, defer, false_positive, duplicate)
   - All `fix` decisions with finding IDs and titles
   - Every `severity_feedback` (`overrated`/`underrated`) — save each as a calibration example (`${CLAUDE_PLUGIN_ROOT}/skills/severity/references/system-rating.md` § Calibration memory)

Findings with `merge_class: out_of_scope_follow_up` never change this PR (`severity` § 5): `fix` means a separate branch and PR, `defer` means an issue, never a `TODO` in this PR's files.

5. For findings marked `fix`: apply the recommended fixes using the finding's `location`, `description`, and `recommendation`. Work through them one at a time, verifying each achieves the desired end-user or developer experience (not just code correctness) before proceeding.

6. `defer` → a `TODO(<slug>)` comment at the location with a descriptive slug and the finding's title (file's native comment syntax), e.g. `// TODO(banner-atomicity): BannerHandle is Send+Sync but read-modify-write is not atomic`. Never the finding ID (`coding-best-practices` bans ephemeral review IDs in committed code); traceability goes in the PR/commit description or a coordinator-kept ID→slug map.

7. `accept_risk` → an `INTENTIONAL(<slug>)` comment at the location with the accepted risk and rationale (from the triage decision, else the finding's description), e.g. `// INTENTIONAL(relaxed-ordering): Relaxed ordering adequate for single-threaded UI model`. Future reviews downgrade a finding near an `INTENTIONAL` comment to INFO — matched by proximity, not slug text.

## Comment-Check Reports

For reports with `metadata.report_type == "comment_check"` (produced by `check-pr-comments`):

- Triage actions apply to unresolved PR review comments instead of code review findings; each is a per-ID decision for `check-pr-comments` § 8 Table mode, which owns replies, resolves, and the gate-thread rule: `fix` → `fix here`, `false_positive`/`accept_risk` → `reject` with the triage reason, `duplicate` → the duplicated ID's decision, asking which ID when `rationale` does not name it (or `handled in #N` when it duplicates a PR/issue), `defer` → `follow-up PR` or `TODO` (ask which), replacing step 6 and the out-of-scope rule above
- `resolve_thread: true` adds "resolve" to that decision (human threads included); otherwise § 8 alone decides

## Output

The report JSON is updated in-place with a `triage` field containing all decisions — consumable by other tools or re-renderable with `generate_review_report.py`.
