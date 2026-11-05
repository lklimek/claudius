---
name: grumpy-review
description: "This skill should be used when the user asks for a \"full review\", \"grumpy review\", or a full code review, audit, or quality assessment, or when a workflow selects full review. It runs independent security, structural, and correctness passes in parallel and produces a deduplicated, severity-ranked report. Ordinary review defaults to basic mode in review-changes."
allowed-tools: Read, Grep, Glob, Write, Bash(git log *), Bash(git diff *), Bash(git status *), Bash(git rev-parse *), Bash(git show *), Bash(mkdir -p /data/tmp/grumpy-*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lint_ephemeral_ids.py *), Agent, SendMessage
---

# Code Review Methodology

Full review: independent specialist workers → consolidated, severity-ranked, deduplicated report. For basic review use [review-changes](../review-changes/SKILL.md). Diff size never changes the selected mode.

## Tone

Claudius/Skippy persona with extra grumpiness about the code — complain, disbelieve obvious mistakes, be opinionated. All written output (report JSON, markdown, HTML) stays strictly professional: grumpiness is for the human; the report is for posterity.

**Argument**: `$ARGUMENTS` — optional scope description (e.g., "feat/zk branch", "packages/auth/", "last 5 commits"). Use `review-changes`'s scope rules: current branch against its base, including local/untracked changes for local review; exact supplied refs for a PR.

## Report Is Mandatory, Even Empty

Always write `report.json` and the requested rendered format, even with zero findings. Run §5 prepare → finalize unconditionally; callers such as `claudius-review-action` treat a missing report as failure. A clean verdict additionally requires complete coverage per §3; an empty findings array does not establish that.

## 1. Scope the Review

Resolve plugin/skill roots from the loaded skill before executing commands; substitute Claude placeholders explicitly on hosts that do not expand them.

**Bash hygiene** (coordinator and producers alike): commands use `<PLACEHOLDER>`s — substitute literal values, one plain command per call; no `$VAR`, `$(…)`, loops, pipes, redirects, `cd`, `git -C` or `python3 -c` (restricted CI allowlists deny them, costing a round each); write files with the Write tool; read plugin files (skills, references, scripts) with Read, never Bash `ls`/`find`/`cp` — CI sandboxes block Bash outside the working directory.

```bash
git rev-parse --verify origin/<BASE>   # <BASE> = base branch; CI checkouts often lack a local copy — try plain <BASE> only if this fails
git log <BASE_REF>..HEAD --oneline     # <BASE_REF> = the ref that verified (e.g. origin/main); use it wherever a base ref is needed below
git diff <BASE_REF>...HEAD --stat      # append `-- <paths>` to scope
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lint_ephemeral_ids.py --range <BASE_REF>...HEAD   # §3 Ephemeral-ID lint
```

Once `<BASE_REF>` is verified, run the other three in one message.

For local review also inspect `git status --short`, `git diff HEAD`, and untracked file contents; include them in the inventory and coverage artifact. The range-based lint does not inspect those local changes, so check their new text separately.

Before spawning reviewers, fix one `<SCRATCH_DIR>` for all producer and intermediate output. If the invoker supplied one (e.g. `claudius-review-action` passes a dir inside the CI sandbox, where `/data/tmp` is blocked), use it verbatim and skip `mkdir`. Otherwise create a collision-resistant one, with a session-specific suffix even when the PR number is known — two coordinators may review the same PR concurrently:

```bash
mkdir -p /data/tmp/grumpy-<PR-number-or-branch>-<session-id-fragment>   # = <SCRATCH_DIR>
```

Use all three core passes for every full review. For 50+ files / 5000+ lines, split their work by module when useful, preserving coverage across boundaries.

## 2. Select Agent Mix

### Core passes

Dispatch through the host's native API: in Claude, the listed identity as the agent type; elsewhere, generic workers. Either way, explicitly supply the listed skill/pass paths and set each model per `delegate` § Token Economy — strong reasoning for all three passes (security, structure, requirements/path analysis). `<role>` is the token used for file names and `prepare` labels.

| Name / Claude identity | `<role>` | Skill / pass | Focus |
|---|---|---|---|
| Smythe / `claudius:security-engineer-smythe` | `security` | `security-best-practices` — Security audit pass | Entry-to-sink security paths, trust boundaries, known vulnerabilities, secrets and dependencies |
| Adams / `claudius:project-reviewer-adams` | `project` | `review-changes` — Adams specialist pass | Cross-artifact consistency, documentation, structure, idioms, maintainability |
| Marvin / `claudius:qa-engineer-marvin` | `qa` | `review-changes` — Reviewer pass and Marvin specialist pass | Requirements, all execution paths, adversarial correctness, tests and lints |

Always include all three, including for tiny diffs. Workers report findings and never fix production code.

### Other conditional agents

| Condition | Name / Claude identity | `<role>` | Skill | Focus |
|---|---|---|---|---|
| Documentation-heavy changes | Trillian / `claudius:technical-writer-trillian` | `docs` | `technical-writing` | Accuracy, completeness, API docs, changelog |

For crypto-heavy code or significant dependency changes, expand the single security-engineer's prompt to include crypto soundness and dependency audit — do NOT spawn a second instance.

### Scaling for large codebases

For 50+ files / 5000+ lines, spawn multiple agents of the same type with different file scopes.

## 3. Craft Agent Prompts

The invariant producer rules — finding format, execution-path coverage, UI-text scan, UX/DX lens, cross-domain hints, collision preservation, Bash hygiene, CI context, process and report-back rules — live in [references/producer-contract.md](references/producer-contract.md); producers read it in place. Never restate them per spawn (measured: ~2500 lines of coordinator output across 5 producers on one large review); `report.json`'s `metadata.plugin_version` pins which version applied. Beyond the general agent prompt requirements (`delegate`), each spawn prompt carries only what varies:

1. **Comparison base**: how to see what changed (`git show <BASE_REF>:<file>`, `git diff <BASE_REF>...HEAD`).
2. **Full roster**: every assigned worker's name, role/focus, scope, and running/queued status. The coordinator owns dispatch; workers never pause for peers or spawn duplicates.
3. **Context Digest** (verbatim, when the invoker supplied one — defined in `review-pr` § Context Digest; never restate or reinvent its contents), with this rule attached — *the digest adjusts scoring (via `claudius:severity`'s non-adversarial `likelihood` recipe), it never suppresses reporting: report the finding with context-adjusted floats, never drop it; a field marked `unknown` changes nothing.*
4. **Worktree isolation (mandatory upfront, not reactive)**: any agent instructed to `git checkout`/build/test the reviewed branch MUST be told to work in a pre-created isolated worktree in its FIRST spawn prompt (`grand-admiral` § Worktree Isolation for setup). A reactive correction arrives too late: the checkout already happened, flipping HEAD under any other agent concurrently reading the same shared tree.
5. **Cross-branch isolation, reviewing sibling PRs in one session**: tell every agent to verify any symbol, function, or API it cites — in findings, positives, or recommendations — actually exists on the branch it was assigned (`git show <its-target-ref>:<file>`), not a sibling branch reviewed in the same session. A shared "positives" blurb or boilerplate recommendation reused across findings is exactly where a sibling branch's content leaks in unnoticed.

Template — copy the paths exactly as they appear here (already resolved to absolute paths; producers never see the placeholders):

```text
In your first message, Read <ROLE_SKILL_AND_PASS_PATHS>, ${CLAUDE_SKILL_DIR}/references/producer-contract.md and ${CLAUDE_PLUGIN_ROOT}/skills/review-changes/references/execution-paths.md[ and <SCRATCH_DIR>/context-digest.md][ and <PATTERN_FILES>] together with your first inputs. Load their explicit dependencies. This is a leaf review pass: do not dispatch peers or re-enter the review coordinator workflow.

Assigned peers (running or queued; the coordinator owns dispatch):
- <teammate-name> — <reviewer role/focus> — <file scope> — <status>
- <teammate-name> — <reviewer role/focus> — <file scope> — <status>

Your role: <role>. Your file scope: <scope>. Write findings to <SCRATCH_DIR>/<role>-findings.json and coverage to <SCRATCH_DIR>/<role>-coverage.md. After writing, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py gate <SCRATCH_DIR>/<role>-findings.json`.
```

- Context-digest part: only when that file was written this run.
- `<ROLE_SKILL_AND_PASS_PATHS>`: absolute paths from §2; for Adams/Marvin include `${CLAUDE_PLUGIN_ROOT}/skills/review-changes/references/specialist-passes.md`.
- `<PATTERN_FILES>`: for the security reviewer — `${CLAUDE_PLUGIN_ROOT}/skills/security-best-practices/references/<lang>-security-patterns.md` for each of `rust`, `go`, `python`, `typescript` the diff touches.

Metadata is coordinator-owned: resolve the actual reviewed commit (`git rev-parse HEAD` or the supplied PR head), not a possibly stale upstream. Supply commit/date/branch/project through `prepare` flags; `--base-ref <BASE_REF>` records the comparison merge-base. Disclose local/untracked changes in coverage and the summary; do not publish a local dirty-tree report as a review of a committed PR head.

`gate` prints `MAX: <band|NONE> BLOCKING: <yes|no>`, the HIGH+/blocker-gate candidate IDs, and band counts; exit 1 (`INVALID:`) means prepare or finalize would reject a finding (missing or wrongly typed field, id or floats; duplicate id; `blocking` without a nonempty `intent_basis`). Exit 2 (`ERROR:`) means the file is unreadable or not a bare array of section objects; `gate` and `prepare` report read errors, including directories and permission failures, without a traceback. Producers end their reply with its output, so the coordinator never opens a findings file to check for an early stop.

### Execution-path coverage

Read [execution-paths.md](../review-changes/references/execution-paths.md). Marvin owns requirements/correctness coverage of every changed unit, Smythe owns security paths; Adams checks structural contracts. Reconcile their coverage artifacts against the full inventory before §5. Scaled scopes must account for cross-module paths. Missing artifacts or unresolved paths make the review incomplete and must appear in the executive summary; zero findings cannot override that status.

### Ephemeral-ID lint

It scans the diff, not findings: run it once before the fan-out, batched with the §1 scope commands. For each hit, judge genuine violation vs quoted/escaped example (a code fence demonstrating the rule, a test fixture asserting it, this lint's own docstring). Dismiss in-skill examples; promote genuine violations to `code_quality` findings with `tags: ["ephemeral-id-reference"]` and ID prefix `CODE-` (coordinator-assigned). Scans exit 0 whatever they find (exit 2 only if `git diff` fails) — judgement is yours. Write promoted hits as their own producer file (e.g. `<SCRATCH_DIR>/lint-findings.json`) and pass it to `prepare`.

## 4. Spawn Agents

Run in a coordinator context with native worker dispatch. If independent workers are unavailable, report that full review cannot run; never silently substitute basic review or a self-review.

Dispatch all core passes independently, in parallel when host capacity permits; otherwise queue the remaining passes. Load `delegate` and `grand-admiral` for briefs, isolation, monitoring, and lifecycle.

**Collect before the turn ends.** Wait for every worker, reconcile coverage, then run §5 through the final report. In Claude headless (`-p`) runs, issue every reviewer `Agent` call in one message and wait in-turn — a headless run ends at the first turn end and abandons background reviewers; interactively, collect every completion before §5; in Codex use the native wait/status tools. Never end with outstanding reviewers.

Honor an explicit user model choice, but before an override would downgrade the security pass below the strong tier, stop and confirm the user really means it — a blanket "review with Sonnet" does not silently trade away security depth. Otherwise retain the strong-model requirement. Report unavailable requested models instead of inventing aliases.

## 5. Consolidate Findings

After all workers complete, scripts do the mechanical work; judgment calls remain coordinator-owned. Run through §5c even when every producer file is `[]`. This pipeline also serves basic review with one producer; use the actual producer list, without launching extra reviewers. Preserve caller-supplied Pass C files in the same consolidation. `<REPORT_DIR>` defaults to the current directory.

### 5a. Prepare

Flatten all agent reports, detect duplicate candidates, scan for INTENTIONAL comments (`<REPO_ROOT>` from `git rev-parse --show-toplevel`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py prepare security:<SCRATCH_DIR>/security-findings.json project:<SCRATCH_DIR>/project-findings.json qa:<SCRATCH_DIR>/qa-findings.json --repo-root <REPO_ROOT> --base-ref <BASE_REF> --output <SCRATCH_DIR>/intermediate.json --digest --commit <COMMIT> --branch <BRANCH>
```

Label each producer file `<role>:<path>` with the §2 token (plus `lint:` and any caller-supplied files, such as Pass C); the label is the `<agent>` in every finding key below. Metadata goes in plain flags (`--commit`, `--branch`, `--project`, `--date`), never JSON on the command line; `project` defaults to the GitHub `owner/repo`, `date` to today (UTC), `--branch` is optional. Make prepare the first call after reviewers return, in the same message as `Skill(claudius:severity)` and a Read of `${CLAUDE_PLUGIN_ROOT}/skills/severity/references/merge-classification.md` (both needed in §5b; skip either if this session already loaded it).

Writes `intermediate.json` (full `raw_findings`, `duplicate_groups`, `intentional_downgrades`, `section_positives`, `agent_stats`; `metadata.plugin_version` auto-filled) and prints `digest.md` — every finding's `<agent>:<original_id>` key, band, floats, location and clipped description, plus duplicate groups and INTENTIONAL hits by key. Decide from the digest (re-read `<SCRATCH_DIR>/digest.md` if the output was truncated); open `intermediate.json` only when a finding's full text matters.

### 5b. Decide (LLM judgment)

1. **Duplicate resolution**: per duplicate group, merge (keep the most detailed description, union tags) or keep separate.
2. **INTENTIONAL downgrade**: downgrade each INTENTIONAL hit to `INFO` (lower its floats) — deliberate engineering decisions from previous triage.
3. **Severity re-evaluation**: load the `severity` skill (`/severity`), then re-assess every finding strictly against its criteria — agents often over-inflate.
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

### 5c. Finalize

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py finalize --input <SCRATCH_DIR>/intermediate.json --decisions <SCRATCH_DIR>/merge-decisions.json --output <REPORT_DIR>/report.json --format md
```

Applies the decisions (writing `<SCRATCH_DIR>/merged-findings.json` for audit), assigns sequential IDs by category, computes `summary_statistics`/`top_findings`/`remediation`, validates against the schema, and renders one file per `--format` (repeatable: `md`, `html`, `pdf`; default `md`) next to `report.json`. All-or-nothing: on failure no report, render, `comments.json`/`body.md` or `merged-findings.json` is written, and any left by an earlier run are renamed to `*.stale`; on success, renders of formats not requested this time are renamed `*.stale` too. Exit 1 names each finding lacking `merge_class`, each invalid decision (e.g. `blocking` without `intent_basis`), each schema error, or a failed render — fix `merge-decisions.json` (or the format) and re-run; exit 2 means an input file is missing or unparseable. After hand-editing `report.json`, re-validate with `validate_report.py <REPORT_DIR>/report.json`.

When presenting results, filter the consolidated findings for `merge_class == "out_of_scope_follow_up"` and name that list to the user as deferral candidates — nothing files them, so an unmentioned deferral is an invisible one (`claudius:severity` § `out_of_scope_follow_up`).

### 5d. Stop reviewer processes

Foreground `Agent` calls that have returned are finished — send them nothing. Only for reviewers spawned as persistent teammates (team/tmux-backed), after consolidation send `SendMessage({to: <name>, message: {type: "shutdown_request"}})` — the structured object, never a JSON string — to each, including ones already marked inactive (`grand-admiral` § Terminating Teammates), then sweep orphaned panes per `grand-admiral`'s `references/stall-watchdog.md` § Orphaned Panes and Processes.

## 6. Iterate if Needed

If the initial review reveals areas needing deeper investigation: spawn additional agents with narrower scope, re-review specific files with different checklists, audit forked dependencies against upstream.

## 7. Additional Report Formats (Optional)

Request HTML/PDF via `finalize --format`; to re-render an existing report: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py <REPORT_DIR>/report.json --format html` (or `pdf`). For interactive triage, use the `claudius:triage-findings` skill with the `<REPORT_DIR>/report.json` path.
