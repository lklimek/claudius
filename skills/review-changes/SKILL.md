---
name: review-changes
description: "This skill should be used when the user asks for a \"code review\", \"review this code\", \"review my changes\", \"review this branch\", \"basic review\", \"full review\", or \"grumpy review\", to \"validate findings\" in a report.json, or when coding-best-practices or git-and-github requires review (changes of at least 50 code lines; every new PR). Basic uses one strong independent reviewer by default. The two-provider gate applies in both modes. Full adds independent security, global-optimum/reuse, and correctness passes. For GitHub PRs use review-pr."
argument-hint: "[basic|full|validate] [scope|report.json]"
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git status *), Bash(git rev-parse *), Bash(git show *), Bash(gh issue view *), Bash(mkdir -p /data/tmp/review-*), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lint_ephemeral_ids.py *), Bash(gh issue list *), Agent, SendMessage
---

# Review Changes

## Modes

- **Basic** (default, including an unspecified “review”): one independent, high-capability reviewer, subject to the two-provider gate below. Verify requirements and all execution paths through the changed code, regardless of diff size.
- **Full** (explicit “full review” or “grumpy review”): independent security, global-optimum/reuse, and adversarial passes on the same coverage baseline. Never downgrade a full review because the diff is small.
- **Validate** (“validate findings”, `validate <report.json>`): skip §1–§4; run the opt-in AI validation pass of §5 on an existing consolidated report.

Arguments: `[basic|full|validate] [scope|report.json]` — scope e.g. "feat/zk branch", "packages/auth/", "last 5 commits". Scope defaults to the whole PR or branch (`<BASE_REF>...<head>`), including working-tree and untracked changes for local work. PR wrappers supply exact refs. In the commands below, use those refs in place of the default base and HEAD. For required pre-push review, use the whole local PR diff for every reviewer model. Record the compared refs/commit and local changes.

Reuse complete independent reviews, or share in-flight ones, only for identical repository, base/head SHAs, scope, mode, requirements/prior decisions and local content. Incremental review needs explicit opt-in, a complete baseline and coverage of changed paths/interactions. It may supplement a required whole-PR review.

### Two-provider gate

PRs touching concurrency, service lifecycle or shutdown, payments or credits, or state machines require two independent reviewers from different providers (Claude, Codex, or agy). Both cover the whole PR at the same current base and head SHAs. In either mode, count reviewers with complete whole-PR coverage and fill any gaps in the pair. Keep the review incomplete until both are done, even if one says MERGEABLE.

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

Gather the user's requirements, acceptance criteria (from the originating issue, read fresh with `gh issue view`, and the task or PR description), relevant specs, and changed files. Carry the caller's Context Digest verbatim when supplied (`review-pr` § Context Digest). Load the project profile (`<SYSTEM_RATING>` § Project profile) and give it to every reviewer, inside the digest when one exists. Mark missing requirements as unknown; never infer intended behavior solely from the implementation.

**Brief** (every reviewer, both modes): pass the maintainer's prior per-ID decisions on this scope verbatim when supplied; they suppress repeats of decided items only (`<MERGE_CLASSIFICATION>` § Previously decided). Put coordinator focus questions last, to be answered after the reviewer's own pass, below its findings.

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

Fix `<REPORT_DIR>` too; an invoker-supplied one wins verbatim. Otherwise, when user or project instructions name a durable review-artifact location, use the absolute path `<that-location>/<repo>/<pr-N-or-branch-slug>-<mode>-<UTC-YYYYMMDD-HHMM>-<session-id-fragment>`; with none named, use `<SCRATCH_DIR>` and tell the user the report's path. Finalize creates it. File names inside stay fixed (`report.json`, renders, `comments.json`, `body.md`): callers key on them.

For the run record (consolidation § Finalize) note the session ID (`${CLAUDE_SESSION_ID}`, or the host's equivalent), the reviewed base and head SHAs, and each reviewer's model with UTC dispatch and return times.

### Ephemeral-ID lint

It scans the diff, not findings: run it once before dispatch, batched with the scope commands. For each hit, judge genuine violation vs quoted/escaped example (a code fence demonstrating the rule, a test fixture asserting it, this lint's own docstring). Dismiss in-skill examples; promote genuine violations to `code_quality` findings with `tags: ["ephemeral-id-reference"]` and ID prefix `CODE-` (coordinator-assigned). Scans exit 0 whatever they find (exit 2 only if `git diff` fails) — judgement is yours. Write promoted hits as their own producer file (e.g. `<SCRATCH_DIR>/lint-findings.json`) and pass it to `prepare`.

## 2. Basic Review

1. Load [delegate](../delegate/SKILL.md) and dispatch the reviewer roster required by Modes and the two-provider gate. Set a strong model explicitly for each reviewer, at high effort where supported (Claude: Opus, preferably the `claudius:qa-engineer-marvin` identity). Apply `delegate` § Independent Verification. Give each reviewer the requirements, scope, § 1 Brief items, § Reviewer pass, and absolute paths to its references.
2. If a required independent reviewer is unavailable, report incomplete coverage. Author self-review and sampled paths leave the independent coverage requirement open.
3. Collect each reviewer's findings and coverage artifact. Verify coverage of every requirement and changed symbol. Run §4 with `qa:<path>` and, for a second provider, `qa-<provider>:<path>`, plus lint and caller-supplied files such as Pass C. Include coverage status in the executive summary.

## 3. Full Review

Follow [full-review.md](references/full-review.md): core passes and models, producer prompt template, coverage reconciliation, spawning.

## 4. Consolidate Findings

Follow [consolidation.md](references/consolidation.md) in both modes for prepare, LLM decisions, finalize, and reviewer cleanup.

## 5. Reports and Validation

Request HTML/PDF via `finalize --format`; to re-render an existing report: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_review_report.py <REPORT_DIR>/report.json --format html` (or `pdf`). For interactive triage, use the `claudius:triage-findings` skill with the `<REPORT_DIR>/report.json` path.

**Validate Findings** (opt-in, coordinator-only, never automatic; `validate` mode): to add `ai_assessment`, `ai_verdict`, and `ai_verdict_confidence` to a consolidated report — and re-estimate floats a partial producer omitted — follow [finding-validation.md](references/finding-validation.md).

## Reviewer pass

Load [coding-best-practices](../coding-best-practices/SKILL.md), [report-format](../report-format/SKILL.md), and [severity](../severity/SKILL.md). Before inspecting source, read [execution-paths.md](references/execution-paths.md) — the shared requirements and path-coverage contract for both modes — and [producer-contract.md](references/producer-contract.md). Outside CI, search project memories (`memcan:recall`) for conventions and known pitfalls first; before finishing, save new durable lessons through `lessons-learned`.

- Verify each requirement against the live implementation and observable behavior. Include happy paths, failures, boundaries, state changes, and interactions with unchanged code.
- Read the full changed functions and affected callers/callees, not just diff hunks. Follow the shared contract without function-count, depth, caller-count, or time sampling.
- **Execution**: for an unpublished head or uncommitted changes, verify locally. For a published head, use its exact-head CI results when they cover the scope. Wait a bounded time for pending runs other than your own review job, and report failures. If automatic triggers miss the scope, use the documented trigger or run affected checks locally. Run tests you write locally. Inside CI, report status only, without waiting or triggering.
- **New tests**: write verification tests only in an isolated worktree. Outside CI, commit those of lasting value for this PR's change (an uncovered contract, a found bug's reproduction) on a branch from the reviewed head and report the commit so the coordinator can publish them; never push.
- **Tests as evidence**: a test counts only once you name the production line whose breakage fails it and confirm its assertions cover the values its name claims. Audit contract coverage and assertion depth: computed values, exact boundaries, specific errors, side effects, ordering, and state consistency. Tests must assert intended behavior rather than mirror implementation; reject `assert result is not None`, `status == 200` without the body, `len(items) > 0` without which items, and "runs without error" without asserting output. Never change expectations to make buggy behavior pass.
- Construct concrete counterexamples for suspected defects. A passing test does not replace path tracing. Record commands, CI runs, results, and anything not executed.
- For shared state, locks, tasks, or channels, enumerate access paths and reason through interleavings, lock order, cancellation, and retries; use race/stress tools where available.
- If you find a trigger for the two-provider gate, record its location in coverage and tell the coordinator so it can complete the reviewer pair.
- Run the producer contract's UI-text scan, always-flagged checks and, when it assigns you, slim-down; apply the UX/DX lens.
- For security-relevant code, load the language pitfalls from [security-best-practices](../security-best-practices/SKILL.md); its full security-audit pass applies only when assigned.
- Write a producer array per `report-format` to the assigned findings file, including `[]` when clean. Write the coverage artifact required by the shared contract even when there are no findings. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/consolidate_reports.py gate <findings-file>`.

## Specialist passes

Full-review workers read [specialist-passes.md](references/specialist-passes.md) for the assigned **Adams** (global optimum and reuse) or **Marvin** (requirements, correctness, and consistency) pass. Identity wrappers load these same passes; generic workers need only the skill.

## QA authoring

Spec-matching QA — writing tests into the repository rather than reviewing — follows [qa-authoring.md](references/qa-authoring.md).
