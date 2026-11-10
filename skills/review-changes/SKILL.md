---
name: review-changes
description: "This skill should be used when the user asks for a \"code review\", \"review this code\", \"review my changes\", \"review this branch\", \"basic review\", \"full review\", or \"grumpy review\", to \"validate findings\" in a report.json, or before completing changes of at least 50 code lines per coding-best-practices. Basic (default) uses one strong independent reviewer; full adds independent security, global-optimum/reuse, and correctness passes into one severity-ranked report. For GitHub PRs use review-pr."
argument-hint: "[basic|full|validate] [scope|report.json]"
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git status *), Bash(git rev-parse *), Bash(git show *), Bash(mkdir -p /data/tmp/review-*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lint_ephemeral_ids.py *), Bash(gh issue list *), Agent, SendMessage
---

# Review Changes

## Modes

- **Basic** (default, including an unspecified “review”): exactly one independent, high-capability reviewer. Verify requirements and all execution paths through the changed code, regardless of diff size.
- **Full** (explicit “full review” or “grumpy review”): independent security, global-optimum/reuse, and adversarial passes on the same coverage baseline. Never downgrade a full review because the diff is small.
- **Validate** (“validate findings”, `validate <report.json>`): skip §1–§4; run the opt-in AI validation pass of §5 on an existing consolidated report.

Arguments: `[basic|full|validate] [scope|report.json]` — scope e.g. "feat/zk branch", "packages/auth/", "last 5 commits". Scope defaults to the current branch against its base, including working-tree and untracked changes for local work; PR wrappers supply exact refs. Record the compared refs/commit and local changes.

The invoking coordinator runs §1–§5. An assigned Adams or Marvin reviewer runs only its pass (§ Reviewer pass, § Specialist passes) and never dispatches peers or re-enters this workflow.

**Tone** (coordinator, full mode): Claudius/Skippy persona with extra grumpiness about the code — complain, disbelieve obvious mistakes, be opinionated. All written output (report JSON, markdown, HTML) stays strictly professional: grumpiness is for the human; the report is for posterity.

**Report is mandatory, even empty**: always write `report.json` and the requested rendered format, even with zero findings. Run consolidation through finalize unconditionally; callers such as `claudius-review-action` treat a missing report as failure. A clean verdict requires complete coverage: missing coverage artifacts or unresolved paths make the review incomplete, stated in the executive summary; zero findings cannot override that.

Review is read-only for production files. Return fixes as recommendations.

### Paths

Resolve plugin/skill roots from the loaded skill before executing commands; substitute Claude placeholders explicitly on hosts that do not expand them. References use these placeholders — substitute the resolved values:

- `<PLUGIN_ROOT>` = `${CLAUDE_PLUGIN_ROOT}`
- `<PRODUCER_READS>` = `${CLAUDE_SKILL_DIR}/references/producer-contract.md` and `${CLAUDE_SKILL_DIR}/references/execution-paths.md`
- `<SPECIALIST_PASSES>` = `${CLAUDE_SKILL_DIR}/references/specialist-passes.md`
- `<SECURITY_PATTERNS_DIR>` = `${CLAUDE_PLUGIN_ROOT}/skills/security-best-practices/references`
- `<MERGE_CLASSIFICATION>` = `${CLAUDE_PLUGIN_ROOT}/skills/severity/references/merge-classification.md`
- `<SYSTEM_RATING>` = `${CLAUDE_PLUGIN_ROOT}/skills/severity/references/system-rating.md`

## 1. Scope the Review

Gather the user's requirements, acceptance criteria, relevant specs, and changed files. Carry the caller's Context Digest verbatim when supplied (`review-pr` § Context Digest). Load the project profile (`<SYSTEM_RATING>` § Project profile) and give it to every reviewer, inside the digest when one exists. Mark missing requirements as unknown; never infer intended behavior solely from the implementation.

**Bash hygiene** (coordinator; producers follow the producer contract's identical rule): commands use `<PLACEHOLDER>`s — substitute literal values, one plain command per call; no `$VAR`, `$(…)`, loops, pipes, redirects, `&&` chains, `cd`, `git -C` or `python3 -c` (restricted CI allowlists deny them, costing a round each); write files with the Write tool; read plugin files (skills, references, scripts) with Read, never Bash `ls`/`find`/`cp` — CI sandboxes block Bash outside the working directory.

```bash
git rev-parse --verify origin/<BASE>   # <BASE> = base branch; CI checkouts often lack a local copy — try plain <BASE> only if this fails
git log <BASE_REF>..HEAD --oneline     # <BASE_REF> = the ref that verified (e.g. origin/main); use it wherever a base ref is needed below
git diff <BASE_REF>...HEAD --stat      # append `-- <paths>` to scope
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lint_ephemeral_ids.py --range <BASE_REF>...HEAD   # § Ephemeral-ID lint
```

Once `<BASE_REF>` is verified, run the other three in one message.

For local review also inspect `git status --short`, `git diff HEAD`, and untracked file contents; include them in the inventory and coverage artifact. The range-based lint does not inspect those local changes, so check their new text separately.

Before dispatching reviewers, fix one `<SCRATCH_DIR>` for all producer and intermediate output, and assign findings/coverage paths. If the invoker supplied one (e.g. `claudius-review-action` passes a dir inside the CI sandbox, where `/data/tmp` is blocked), use it verbatim and skip `mkdir`. Otherwise create a collision-resistant one, with a session-specific suffix even when the PR number is known — two coordinators may review the same PR concurrently:

```bash
mkdir -p /data/tmp/review-<PR-number-or-branch>-<session-id-fragment>   # = <SCRATCH_DIR>
```

### Ephemeral-ID lint

It scans the diff, not findings: run it once before dispatch, batched with the scope commands. For each hit, judge genuine violation vs quoted/escaped example (a code fence demonstrating the rule, a test fixture asserting it, this lint's own docstring). Dismiss in-skill examples; promote genuine violations to `code_quality` findings with `tags: ["ephemeral-id-reference"]` and ID prefix `CODE-` (coordinator-assigned). Scans exit 0 whatever they find (exit 2 only if `git diff` fails) — judgement is yours. Write promoted hits as their own producer file (e.g. `<SCRATCH_DIR>/lint-findings.json`) and pass it to `prepare`.

## 2. Basic Review

1. Load [delegate](../delegate/SKILL.md), then dispatch **one** worker with a strong available reasoning model at high effort where supported, setting the model explicitly (Claude: Opus, preferably the `claudius:qa-engineer-marvin` identity; Codex: a high-capability model available in the current session). Select independently of the author's model; never substitute a lightweight model for a small diff. Give it the requirements, scope, § Reviewer pass, and absolute paths to the references it names.
2. If independent workers are unavailable, report that limitation; do not describe an author self-review as an independent basic review. A host-imposed budget does not permit sampling paths and calling the review complete.
3. Collect the findings and coverage artifact, verify that every requirement and changed symbol is accounted for, and run §4 with the reviewer's file as `qa:<path>`, plus the lint file and caller-supplied files such as Pass C. Include the coverage status in the executive summary.

## 3. Full Review

Follow [full-review.md](references/full-review.md): core passes and models, producer prompt template, coverage reconciliation, spawning.

## 4. Consolidate Findings

Follow [consolidation.md](references/consolidation.md): prepare, LLM decisions, finalize, stop reviewers. It also serves basic mode with its single producer.

## 5. Reports and Validation

Request HTML/PDF via `finalize --format`; to re-render an existing report: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py <REPORT_DIR>/report.json --format html` (or `pdf`). For interactive triage, use the `claudius:triage-findings` skill with the `<REPORT_DIR>/report.json` path.

**Validate Findings** (opt-in, coordinator-only, never automatic; `validate` mode): to add `ai_assessment`, `ai_verdict`, and `ai_verdict_confidence` to a consolidated report — and re-estimate floats a partial producer omitted — follow [finding-validation.md](references/finding-validation.md).

## Reviewer pass

Load [coding-best-practices](../coding-best-practices/SKILL.md), [report-format](../report-format/SKILL.md), and [severity](../severity/SKILL.md). Before inspecting source, read [execution-paths.md](references/execution-paths.md) — the shared requirements and path-coverage contract for both modes — and [producer-contract.md](references/producer-contract.md). Outside CI, search project memories (`memcan:recall`) for conventions and known pitfalls first; before finishing, save new durable lessons through `lessons-learned`.

- Verify each requirement against the live implementation and observable behavior. Include happy paths, failures, boundaries, state changes, and interactions with unchanged code.
- Read the full changed functions and affected callers/callees, not just diff hunks. Follow the shared contract without function-count, depth, caller-count, or time sampling.
- **Execution, CI first**: when CI runs the relevant tests and lints for the reviewed head, do not re-run them locally; before finishing, check that head's CI (`gh pr checks <PR>` or `gh run list --commit <sha>`), wait a bounded time for pending runs other than your own review job, and report failures. When automatic triggers miss the changed scope (path filters, manual or label-gated workflows), trigger the relevant workflow (`gh workflow run`, documented label or comment). Run locally only when no CI exists, CI cannot cover the scope, the reviewed changes are uncommitted, or for tests you wrote. Inside a CI review run, report CI status only (where `gh` is permitted), without waiting or triggering.
- **New tests**: write verification tests only in an isolated worktree. Outside CI, commit those of lasting value for this PR's change (an uncovered contract, a found bug's reproduction) on a branch from the reviewed head and report the commit so the coordinator can publish them; never push.
- Construct concrete counterexamples for suspected defects. A passing test does not replace path tracing. Record commands, CI runs, results, and anything not executed.
- For shared state, locks, tasks, or channels, enumerate access paths and reason through interleavings, lock order, cancellation, and retries; use race/stress tools where available.
- Scan user-visible strings for misleading or alarming errors and apply the UX/DX lens.
- For security-relevant code, load the language pitfalls from [security-best-practices](../security-best-practices/SKILL.md); its full security-audit pass applies only when assigned.
- Write a producer array per `report-format` to the assigned findings file, including `[]` when clean. Write the coverage artifact required by the shared contract even when there are no findings. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py gate <findings-file>`.

## Specialist passes

Full-review workers read [specialist-passes.md](references/specialist-passes.md) for the assigned **Adams** (global optimum and reuse) or **Marvin** (requirements, correctness, and consistency) pass. Identity wrappers load these same passes; generic workers need only the skill.

## QA authoring

Spec-matching QA — writing tests into the repository rather than reviewing — follows [qa-authoring.md](references/qa-authoring.md).
