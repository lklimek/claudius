# Full Review

Run in a coordinator context with native worker dispatch. If independent workers are unavailable, report that full review cannot run; never silently substitute basic review or a self-review.

## Core passes

Dispatch through the host's native API: in Claude, the listed identity as the agent type; elsewhere, generic workers. Either way, explicitly supply the listed skill/pass paths and set each model per `delegate` § Token Economy — strong reasoning for all three passes (security, global optimum and reuse, requirements/path analysis); Adams' cross-repository reading needs a large-context model (Claude: Opus, 1M). `<role>` is the token used for file names and `prepare` labels.

| Name / Claude identity | `<role>` | Skill / pass | Focus |
|---|---|---|---|
| Smythe / `claudius:security-engineer-smythe` | `security` | `security-best-practices` — Security audit pass | Entry-to-sink security paths, trust boundaries, known vulnerabilities, secrets and dependencies |
| Adams / `claudius:project-reviewer-adams` | `project` | `review-changes` — Adams specialist pass | Local-vs-global optimum: fix in the owning layer/repository across the organization; DRY of new code and tests |
| Marvin / `claudius:qa-engineer-marvin` | `qa` | `review-changes` — Reviewer pass and Marvin specialist pass | Requirements, all execution paths, adversarial correctness, cross-artifact consistency, structure and idioms, CI status |

Always include all three, including for tiny diffs. Documentation-heavy changes add Trillian / `claudius:technical-writer-trillian` (`docs`, `technical-writing`: accuracy, completeness, API docs, changelog). For crypto-heavy code or significant dependency changes, expand the security prompt to crypto soundness and dependency audit — do NOT spawn a second instance. For 50+ files / 5000+ lines, spawn multiple agents of the same type with different file scopes, preserving coverage across boundaries.

## Agent prompts

The invariant producer rules — finding format, execution-path coverage, UI-text scan, UX/DX lens, cross-domain hints, collision preservation, Bash hygiene, CI context, process and report-back rules — live in the producer contract (`<PRODUCER_READS>`); producers read it in place. Never restate them per spawn (measured: ~2500 lines of coordinator output across 5 producers on one large review); `report.json`'s `metadata.plugin_version` pins which version applied. Beyond the general agent prompt requirements (`delegate`), each spawn prompt carries only what varies:

1. **Comparison base**: how to see what changed (`git show <BASE_REF>:<file>`, `git diff <BASE_REF>...HEAD`).
2. **Full roster**: every assigned worker's name, role/focus, scope, and running/queued status. The coordinator owns dispatch; workers never pause for peers or spawn duplicates.
3. **Context Digest** (verbatim, when the invoker supplied one — defined in `review-pr` § Context Digest; never restate or reinvent its contents), with this rule attached — *the digest adjusts scoring (via `claudius:severity`'s non-adversarial `likelihood` recipe), it never suppresses reporting: report the finding with context-adjusted floats, never drop it; a field marked `unknown` changes nothing.*
4. **Worktree isolation (mandatory upfront, not reactive)**: any agent instructed to `git checkout`/build/test the reviewed branch MUST be told to work in a pre-created isolated worktree in its FIRST spawn prompt (`grand-admiral` § Worktree Isolation for setup). A reactive correction arrives too late: the checkout already happened, flipping HEAD under any other agent concurrently reading the same shared tree.
5. **Cross-branch isolation, reviewing sibling PRs in one session**: tell every agent to verify any symbol, function, or API it cites — in findings, positives, or recommendations — actually exists on the branch it was assigned (`git show <its-target-ref>:<file>`), not a sibling branch reviewed in the same session. A shared "positives" blurb or boilerplate recommendation reused across findings is exactly where a sibling branch's content leaks in unnoticed.

Template — substitute every path placeholder with its resolved absolute value from `review-changes` § Paths; producers never see the placeholders:

```text
In your first message, Read <ROLE_SKILL_AND_PASS_PATHS>, <PRODUCER_READS>[ and <SCRATCH_DIR>/context-digest.md][ and <PATTERN_FILES>] together with your first inputs. Load their explicit dependencies. This is a leaf review pass: do not dispatch peers or re-enter the review coordinator workflow.

Assigned peers (running or queued; the coordinator owns dispatch):
- <teammate-name> — <reviewer role/focus> — <file scope> — <status>
- <teammate-name> — <reviewer role/focus> — <file scope> — <status>

Your role: <role>. Your file scope: <scope>. Write findings to <SCRATCH_DIR>/<role>-findings.json and coverage to <SCRATCH_DIR>/<role>-coverage.md. After writing, run `python3 <PLUGIN_ROOT>/scripts/consolidate_reports.py gate <SCRATCH_DIR>/<role>-findings.json`.
```

- Context-digest part: only when that file was written this run.
- `<ROLE_SKILL_AND_PASS_PATHS>`: `<PLUGIN_ROOT>/skills/<skill>/SKILL.md` for the role's skill in the core-passes table; for Adams/Marvin add `<SPECIALIST_PASSES>`.
- `<PATTERN_FILES>`: for the security reviewer — `<SECURITY_PATTERNS_DIR>/<lang>-security-patterns.md` for each of `rust`, `go`, `python`, `typescript` the diff touches.

Metadata is coordinator-owned: resolve the actual reviewed commit (`git rev-parse HEAD` or the supplied PR head), not a possibly stale upstream. Supply commit/date/branch/project through `prepare` flags; `--base-ref <BASE_REF>` records the comparison merge-base. Disclose local/untracked changes in coverage and the summary; do not publish a local dirty-tree report as a review of a committed PR head.

`gate` prints `MAX: <band|NONE> BLOCKING: <yes|no>`, the HIGH+/blocker-gate candidate IDs, and band counts; exit 1 (`INVALID:`) means prepare or finalize would reject a finding (missing or wrongly typed field, id or floats; duplicate id; `blocking` without a nonempty `intent_basis`). Exit 2 (`ERROR:`) means the file is unreadable or not a bare array of section objects; `gate` and `prepare` report read errors, including directories and permission failures, without a traceback. Producers end their reply with its output, so the coordinator never opens a findings file to check for an early stop.

## Execution-path coverage

Per the execution-paths contract (`<PRODUCER_READS>`): Marvin owns requirements/correctness coverage of every changed unit, Smythe owns security paths; Adams records the layers and repositories checked per changed unit. Reconcile their coverage artifacts against the full inventory before consolidation. Scaled scopes must account for cross-module paths.

## Spawn

Dispatch all core passes independently, in parallel when host capacity permits; otherwise queue the remaining passes. Load `delegate` and `grand-admiral` for briefs, isolation, monitoring, and lifecycle.

**Collect before the turn ends.** Wait for every worker, reconcile coverage, then run consolidation through the final report. In Claude headless (`-p`) runs, issue every reviewer `Agent` call in one message and wait in-turn — a headless run ends at the first turn end and abandons background reviewers; interactively, collect every completion before consolidation; in Codex use the native wait/status tools. Never end with outstanding reviewers.

Honor an explicit user model choice, but before an override would downgrade the security pass below the strong tier, stop and confirm the user really means it — a blanket "review with Sonnet" does not silently trade away security depth. Otherwise retain the strong-model requirement. Report unavailable requested models instead of inventing aliases.

If the review reveals areas needing deeper investigation: spawn additional agents with narrower scope, re-review specific files with different checklists, audit forked dependencies against upstream.
