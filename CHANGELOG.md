# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [5.0.3] - 2026-07-03

### Changed

- **`agents/architect-nagatha.md`, `agents/developer-bilby.md`, `agents/project-reviewer-adams.md`, `agents/qa-engineer-marvin.md`, `agents/security-engineer-smythe.md`, `agents/technical-writer-trillian.md`, `agents/ux-designer-diziet.md`**: every specialist's Voice section now requires concise, precise, formal output — no obvious or redundant explanations — since Claudius alone talks to the user. Trillian's published documentation deliverables (README, guides, changelogs) are exempted; only its reports/comments/commit messages are affected.
- **`agents/claudius.md`**: added an explicit translation duty — Claudius must unpack terse specialist output into clear, friendly, in-character explanation before it reaches the user, never relay it verbatim.

## [5.0.2] - 2026-07-02

### Fixed

All 15 MEDIUM findings from the same-day whole-repo self-audit (PR #56; audit 2026-07-02), fixed by 5 worktree-isolated `developer-bilby` agents and merged:

- **`hooks/block-github-writes.sh`**: rebuilt as a default-deny allowlist (was a denylist that silently permitted any unlisted write tool, including the newly-enabled `dependabot`/`code_security`/`secret_protection`/`security_advisories` toolsets). Malformed/empty/non-object stdin and a missing `jq` now emit an explicit deny instead of crashing to a non-blocking exit code that Claude Code's hook contract treats as ALLOW. 16 new regression tests (`tests/test_block_github_writes.sh`).
- **`scripts/generate_review_report.py`**: HTML sanitiser migrated from the deprecated/EOL `bleach` to `nh3` (allowlist behavior preserved exactly, plus nh3's safer `rel="noopener noreferrer"` default kept). Chart.js vendored and inlined (was fetched unpinned from a CDN with no SRI) so generated reports are genuinely self-contained and render offline. +10 new tests.
- **`scripts/severity_util.py`, `scripts/consolidate_reports.py`, `scripts/validate_report.py`**: `derive_overall()` now rejects non-finite `risk`/`impact`/`scope` values (a `NaN`/`Infinity` previously derived `severity: 1` silently, dropping the finding from `top_findings`/`remediation` while `assemble`/`validate_report.py` both reported success); `generate_top_findings()` no longer crashes with a raw `KeyError` on a missing `title`/`location` field; `write_text` no longer crashes with `UnicodeEncodeError` on lone Unicode surrogates; `find_duplicate_groups()` gets a threshold-gated fast path (unchanged exact O(n²) algorithm below 500 findings, a bucketed-plus-exact-title-match algorithm with a logged warning above it — never a silent behavior change). +35 new tests.
- **`scripts/gh-fetch-reviews.sh`, `scripts/gh-post-review.sh`, `scripts/gh-list-review-threads.sh`, `scripts/gh-resolve-review-threads.sh`**: `gh-fetch-reviews.sh` and `gh-list-review-threads.sh` now paginate (were silently truncating past GitHub's default page size / a hardcoded `first: 100`, live-verified 40%/86% of results dropped on real PRs); `gh-post-review.sh`'s ghsudo permission-retry now buffers and replays the request body instead of piping it (the retry was silently posting an empty review after the first `gh` call drained stdin — same fix applied to the duplicated, currently-dormant copy of the helper in `gh-resolve-review-threads.sh`); `gh-resolve-review-threads.sh`'s `--path` glob-to-regex conversion now escapes the full regex metacharacter set (was silently failing to match real filenames like `pages/[id].tsx`). +18 new tests.
- **`tests/test_agent_watchdog_gone.sh`**: added the zero-tmux-backed-teammate scenario — the exact input shape that produced the PR #54 `OUR_PANE_TYPE` unbound-variable crash — which no prior scenario exercised; the existing suite would have kept passing even with that fix reverted.
- **`schemas/review-report.schema.json`, `skills/report-format/SKILL.md`**: `scope`'s schema description realigned from the stale "1.0 in-diff" PR-relevance definition to the `severity` skill's blast-radius definition (also found and fixed a third live copy of the stale definition in `report-format/SKILL.md`'s Required Fields table, and a stale "sanitised through `bleach`" mention).
- **`SETUP.md`**: agent roster updated for the v5.0.0 crew restructuring — Adams' and Marvin's rows now state their structural/idiom and adversarial/execution-focused code-quality roles, matching their own current agent files.
- **`skills/report-format/SKILL.md`**: added a standalone-producer carve-out to the `location_permalink` DO-NOT-emit rule, reconciling it with `check-pr-comments`' already-correct requirement to emit it when no coordinator derive-pass runs.

A follow-up solo re-review (same PR, single `project-reviewer-adams` agent, no fan-out) independently re-verified all 15 fixes above hold, then surfaced 15 new LOW findings — several self-inflicted by the fix wave itself — fixed by 4 more worktree-isolated `developer-bilby` agents and merged into the same PR:

- **`hooks/block-github-writes.sh`**: allowlist gained the enabled `context` toolset's read-only tools (`get_me`, `get_teams`, `get_team_members`), closing a spurious-denial trap; comment corrected to list all nine enabled toolsets.
- **`.github/workflows/test-report-pipeline.yml`, `.github/workflows/notify-marketplace.yml`**: added least-privilege `permissions:` blocks and pinned actions to full commit SHAs (verified against the live GitHub API); added a `ruff format --check .` gate.
- **`scripts/generate_review_report.py`**: vendored Chart.js hash is now asserted by a test (`sha256` recomputed fresh from the real file), not just documented in a comment — a tampered vendor file now fails CI.
- **`scripts/triage_server.py`**: wired the non-finite-JSON guard (added earlier in this same PR for the other report-loading call sites) into the triage server's report load path, the one site the original fix missed.
- **`scripts/consolidate_reports.py`**: deduplicated the earlier-in-this-PR duplicate-detection fix's graph-traversal BFS (was implemented twice); the degraded (>500-finding) dedup path now caps per-bucket fuzzy scans, closing a residual stall under a single dominant `(category, file_path)` bucket.
- **`scripts/severity_util.py`**: `_effective_severity` now prefers the derived band from `risk`/`impact`/`scope` over a conflicting explicit integer, matching the coordinator's precedence and the `severity` skill's doctrine; dropped a dangling internal `TODO` token.
- **`scripts/gh-resolve-review-threads.sh`**: `--path` glob matching is now anchored (was unanchored substring search — `*.rs` matched `main.rson`, `src/*.ts` matched `backup/src/a.ts`).
- **`scripts/gh-list-review-threads.sh`, `scripts/gh-resolve-review-threads.sh`, `scripts/gh-post-review.sh`**: extracted shared `scripts/gh-common.sh` (`run_gh` + cursor-pagination walk) — the two had already drifted independently since the MEDIUM fix wave.
- **`skills/report-format/SKILL.md`**: "Report Pipeline Tools" table no longer documents two commands that fail as written; now points to `grumpy-review`'s canonical invocation forms.
- **`agents/technical-writer-trillian.md`, `agents/developer-bilby.md`**: `severity` skill moved from Bilby (implementation-only, no longer reviews) to Trillian (a finding-producing agent that was missing it).
- **`pyproject.toml`** (new), plus a repo-wide `ruff format` pass: formatter config was previously uncommitted and unenforced.
- **`skills/check-pr-comments/SKILL.md`**: corrected a factually-wrong rationale for omitting `metadata.repository`.
- **`skills/git-and-github/SKILL.md`, `skills/review-loop/SKILL.md`**: the canonical commit-trailer example hardcoded a specific model name and had already gone stale, causing 6 of this PR's own commits to be misattributed; now instructs substituting the agent's actual current model, and the duplicate copy was removed in favor of the single source.

## [5.0.1] - 2026-07-02

### Fixed

- `check-pr-comments`: agents were re-verifying threads GitHub already reports as resolved (`isResolved: true`), re-reading code and re-running call-tree walks on settled questions. Step 3 now trusts `isResolved` and skips verification entirely for already-resolved threads; the summary (step 4), report finding format (step 5), and resolve/reply matrix (step 8) updated to match — already-resolved threads are reported/left as-is without a restated fix assessment or a redundant reply/resolve action.

## [5.0.0] - 2026-07-01

### Changed

- **BREAKING: `grumpy-review`'s agent mix is now a fixed 3-agent core trio** — `security-engineer-smythe` (opus, unchanged), `project-reviewer-adams` (opus, promoted from sonnet), `qa-engineer-marvin` (sonnet, demoted from opus) are ALWAYS included in every non-trivial review, regardless of size or language. The former "Language specialists" table (Rust/Go/Python/Frontend → `developer-bilby`) is removed — there is no more per-language conditional agent. Adams and Marvin instead preload the matching `*-best-practices` skill(s) for the language(s) in scope, the same mechanism `developer-bilby` used to use.
- **`project-reviewer-adams` absorbs the "structural/idiom/consistency" half of `developer-bilby`'s former code-quality review remit** — readability, naming, DRY, structural consistency, maintainability, cross-file duplication — on top of its existing project-consistency and specialist-orchestration role. Model default flipped `sonnet` → `opus` (agent frontmatter + `grand-admiral` Token Economy) to match the heavier remit. Its own pre-existing "Test Depth" checklist (near-duplicate of Marvin's) is narrowed to a lighter, reading-only check to remove redundant overlap. Code Quality Review Scope additionally names redundant/over-engineered data structures as an explicit example category, and re-homes a reading-only "zero test coverage on a new public/cross-boundary surface" flag that the Test Depth narrowing had otherwise dropped without a new owner (found via a real-PR A/B validation run against the pre-restructure crew).
- **`qa-engineer-marvin` absorbs the "adversarial/correctness/execution" half** — actually running tests and lints, edge cases, ownership/panic/error-handling bugs, independent verification against ground truth (git history, live repo/branch state) rather than trusting a diff or another report. Model default flipped `opus` → `sonnet` (agent frontmatter + `grand-admiral` Token Economy) — an internal Opus-vs-Sonnet-5 review experiment showed Sonnet 5 matching Opus on review depth and leading on exactly this independent-verification behavior. In `workflow-feature`/`workflow-simplified`, Marvin's QA-phase remit narrows to ONLY the adversarial Tests/spec-verification pass — the former Docs-review and Dedup-audit sub-passes move to `project-reviewer-adams`. `workflow-trivial` drops both passes outright at its scope (no reassignment) since `project-reviewer-adams` remains omitted there for size reasons; Bilby's existing Phase 2 self-checks plus merge-time review remain the safeguard.
- Both new code-quality sections in Adams' and Marvin's agent files are self-contained — each states its own scope boundary directly (evidence-based: "flag what's provable by reading alone" vs. "flag only what's provable by execution") rather than deferring to the other agent's file, since there is no runtime mechanism for one agent to look up another's prompt.
- **`grumpy-review` trivial-review fallback is now tier-aware**: the single stand-in reviewer for a trivial (<200 line) review is chosen for maximum independence from the code's authoring tier — `qa-engineer-marvin` (sonnet) when the code was authored on Opus, `project-reviewer-adams` (opus) when authored on Sonnet, defaulting to Marvin when the authoring tier can't be determined (human-authored code, unclear git history).
- **`grumpy-review` model-override policy**: a user-requested uniform model override across the review trio now requires an explicit confirmation step before it is allowed to downgrade `security-engineer-smythe` below `opus` — security depth is no longer silently tradeable away by a blanket model request.
- `workflow-simplified`'s security pass is now unconditional ("Security audit", not "if security-relevant change"), matching `grumpy-review`'s always-core treatment of `security-engineer-smythe`.
- `report-format` ID-prefix table: `CODE-`/`RUST-`/`PY-`/`GO-`/`FE-` are reassigned from sole ownership by `developer-bilby` to joint ownership by `project-reviewer-adams` and `qa-engineer-marvin` — the prefix now identifies a finding category/language, not a single agent identity.
- `grand-admiral` Crew Roster: dropped "language reviews" from Bilby's row (no longer accurate); Adams' row gains "structural/idiom code quality"; Marvin's row drops "duplication" (moved to Adams). Token Economy model tiering: `qa-engineer-marvin` moved from the Opus bullet to the Sonnet 5 bullet; `project-reviewer-adams` moved from the Sonnet 5 bullet to the Opus bullet, matching the flips above. The "Bilby vs Marvin" QA-loop doctrine line drops "code duplication" from the list of things Marvin proves wrong (that pass moved to Adams) — the rest of the doctrine (Bilby builds/Marvin breaks/never fixes/fixes route back to Bilby) is unaffected.
- `README.md` and `SETUP.md`: removed references to `developer-bilby` performing code reviews and to "language-specific reviewers" as a distinct `grumpy-review` agent category — both are now inaccurate.

### Removed

- **`developer-bilby` no longer participates in code review in any capacity** — implementation-only from now on. Removed from `grumpy-review`'s agent mix (both the trivial single-agent fallback and the former per-language conditional table), from `report-format`'s ID-prefix ownership, and from `project-reviewer-adams`'/`security-engineer-smythe`'s specialist-delegation lists. Its own "Code Review Mode" section is deleted.

## [4.13.1] - 2026-07-01

### Fixed

- `agent-watchdog.sh`: fixed a crash-on-every-run under `set -u` — `OUR_PANE_TYPE` (an associative array populated only for tmux-backed teammates) throws "unbound variable" on `${#OUR_PANE_TYPE[@]}` when no member is ever assigned into it (e.g. a run with zero tmux-backed teammates, only plain background `Agent(name=...)` spawns). Reproduced in isolation (`set -u; declare -A X; "${#X[@]}"` → unbound) and fixed by seeding-then-deleting a dummy key right after `declare -A`, which makes bash treat the array as touched. `bash -n` + `shellcheck -S style` clean.

## [4.13.0] - 2026-07-01

### Changed

- **Model tiering re-based on Claude Sonnet 5** (released 2026-06-30). Sonnet 5 reaches ~91% of Opus 4.8 on SWE-bench Pro with best-in-class terminal/computer-use (Terminal-bench, OSWorld 81%) and native 1M context at ~1.67× lower cost (2.5× until 2026-08-31), so it becomes the fleet's default workhorse. `grand-admiral` Token Economy §2 rewritten: per-agent `model` fallbacks now encode where quality is load-bearing, with per-spawn override still mandatory, the risk-based tiebreaker strengthened (all security-sensitive work — including dependency/version bumps, regardless of a passing vulnerability scan — escalates to Opus, with full bump investigation always required; `dependabot-merge` updated to match), and a new Sonnet 5 tokenizer caveat (1.0–1.35× more tokens than Sonnet 4.6).
- `claudius` coordinator model `opus[1m]` → `sonnet[1m]`: the every-session lead moves to Sonnet 5 (native 1M, most-agentic Sonnet, stronger self-verification) — the single largest cost reduction, since the coordinator was the top Opus consumer in real usage.
- Agent frontmatter `model` defaults set explicitly (were `inherit`, which silently fell back to the coordinator's Opus tier): `developer-bilby`, `qa-engineer-marvin`, `architect-nagatha`, `ux-designer-diziet`, `security-engineer-smythe` → `opus` (agentic coding, QA depth, design, UX, security/high-risk); `project-reviewer-adams`, `technical-writer-trillian` → `sonnet` (review, docs). The cheap tier is now the default for the light seats and the quality tier the default for the heavy ones — a forgotten override no longer silently lands review/docs work on Opus.
- `security-best-practices` skill `model: opus` → `inherit`: security work now follows the invoking agent's tier — Opus for `security-engineer-smythe`'s real audits, Sonnet 5 for routine consults (clean dependency bumps, mechanical review) — matching the risk-based tiebreaker.

## [4.12.0] - 2026-06-25

### Changed

- `agent-watchdog.sh` + `grand-admiral` Recovery: the stall watchdog now covers **shared-cwd team agents** (e.g. read-only design/QA agents living in the lead's cwd) that it previously skipped — when a member's worktree/cwd activity clock can't be isolated, it falls back to the member's own **transcript-jsonl mtime**. Adds **process-liveness GONE detection**, distinct from STALL: a tmux pane that dropped to a bare shell (`pane-dead`), a vanished pane/PID (`pid-gone`), or a stale `isActive` with no live process and no transcript advance (`stale-active`) emits `GONE agent=<name> reason=…` after `--gone-polls` consecutive confirmations — never auto-killing a live process (GONE only flags a stale active flag to clear or a respawn to consider), with `RESUMED … reason=recovered` when a pane goes live again. New `--no-gone` disables the layer (default on; silent no-op when tmux/config absent). GONE introspects the agent's **per-session tmux swarm socket** (`claude-swarm-<pid>`, discovered and positively session-bound by matching each member's pane-id + agentType — collision-safe across concurrent sessions), so it functions in the real harness where `$TMUX` is unset and agent panes are off tmux's default socket. Covered end-to-end by `tests/test_agent_watchdog_gone.sh` against real tmux servers. Existing STALL/RESUMED grammar and flags preserved; `bash -n` + `shellcheck -S style` clean.
- `agent-watchdog.sh` + `grand-admiral` Multi-Session Hygiene: the watchdog is now **session-scoped**, fixing a recurring failure where it bound to another concurrent session's team on a shared host (it picked the newest `~/.claude/teams/session-*` dir by mtime, silently monitoring strangers' agents and missing its own). New `--session-id <id>` flag, precedence `--team-dir` > `--session-id` > `$CLAUDE_SESSION_ID` env > newest-mtime (last resort, now with a one-time stderr warning naming the chosen session, its `leadSessionId`, and the candidate count). All downstream discovery — members, tmux panes, transcripts, task ownership — is scoped to the selected team's `leadSessionId`; cross-session artifacts are rejected (it skips on genuine ambiguity rather than mis-binding). The Monitor one-liner now passes `--session-id ${CLAUDE_SESSION_ID}`, and a new grand-admiral Multi-Session Hygiene rule extends the discipline to manual investigation (scope `ps`/`/proc`/config/worktree lookups to your own session id; never assume the newest artifact on the box is yours).
- `claudius` agent: relaxed the absolute "never implement" coordinator rule to a **context-cost delegation threshold**. The coordinator now handles bounded, low-context work inline (one-line fixes, a few targeted edits, doc tweaks, quick reads) and reserves spawning for parallel, high-risk, or context-heavy work (large files, logs, wide searches, multi-file changes) that would pollute its context. The deciding axis is context cost, not task type. Programme-manager mode (cross-repo) stays strictly no-implementation.
- `grand-admiral` Team Lifecycle: added **Terminating Teammates** doctrine — a named `Agent(name=...)` teammate is NOT in the background-task registry, so `TaskStop` on it (by `name` or `name@session-...`) always returns "No task found", which looks like an id-lookup bug but is the wrong subsystem. Shut teammates down only via `SendMessage({type: "shutdown_request"})`. Documents the stuck-teammate escalation (surface to the user via `/tasks`/tmux; don't retry `TaskStop` or burn turns on each idle ping) and the named-vs-`run_in_background` spawn trade-off (mid-run `SendMessage` steering vs. a clean `TaskStop`-able registry id).
- `grand-admiral` Worktree Isolation: the post-wave push is now performed **directly by the coordinator** (plain `git push`, falling back to `ghsudo git push` on 403/no-write-access, then verify with `git ls-remote`) once the user authorizes it — never relayed to a dev agent, which loops or refuses when push authorization arrives second-hand via SendMessage instead of straight from the user.
- `rust-best-practices` Common Pitfalls: added a rule against relying on `debug_assert!`/`debug_assert_eq!`/`cfg(debug_assertions)` for correctness or safety invariants — they compile out in release builds. Validate at runtime and return a typed error; `panic!`/`assert!` are not an acceptable default, reserved only for genuinely unrecoverable invariant violations.
- **`coding-best-practices` loading strengthened across the agent roster**: the skill was preloaded via every agent's `skills:` frontmatter, but only `developer-bilby` and `project-reviewer-adams` carried an explicit body directive to follow it (and `security-engineer-smythe`'s own Skills list omitted it). Added a uniform **MANDATORY** directive to all seven specialist agents plus a coordinator clause in `claudius` — load `/coding-best-practices` at task start and apply it continuously as they work (not a one-time read) for any code written, modified, reviewed, or tested. Reinforced in `grand-admiral` (Session Protocol + new Agent Prompt Requirement #11: every code-touching brief must state the requirement) and in the skill's own description.

### Fixed

- `gh-request-reviewer.sh` used the invalid `gh pr edit "owner/repo#num"` selector — `gh` reads `owner/repo#num` as a branch and fails ("no pull requests found for branch …"). Now uses the correct `gh pr edit "$pr_number" --repo "$owner_repo" --add-reviewer …` form, fixing every reviewer request (including `@copilot`).
- Skill instruction bodies (`git-and-github`, `ci-dance`, `triage-findings`) invoked `gh-*.sh` helper scripts by bare filename — not on `$PATH` and ambiguous across cached plugin versions, forcing agents to `find` and guess the right copy. They now use the portable `${CLAUDE_SKILL_DIR}/../../scripts/<name>.sh` path, consistent with the reference files and the `grand-admiral` watchdog convention.

## [4.11.0] - 2026-06-16

### Added

- `scripts/agent-watchdog.sh` — a persistent agent-stall watchdog for the Monitor tool, filling the one gap the harness does not auto-notify on: a NAMED agent that owns assigned work yet has gone silent. A stall is **owning an in_progress task AND idle (≥) the threshold AND no build running *under that agent***, NOT bare idle — a healthy agent idles while waiting for its next instruction, and an idle agent with no in_progress task is never flagged. "Owns work" is read each poll from the on-disk task store (`~/.claude/tasks/<teamName>/<id>.json`, derived from the team config `name`; `owner`+`status` fields are the source of truth). Build suppression is **per-agent**: only when an agent is otherwise about to STALL, `/proc` is scanned for a process whose `/proc/<pid>/cwd` is under the agent's worktree/cwd running an anchored build/test argv (cargo build|test|check|clippy|run, rustc, cc1/cc1plus, gcc, g++, clang/clang++, ld, make, cmake, ninja, gradle/gradlew, mvn/mvnw, bazel, go build|test|run, tsc, webpack, pytest, jest, dotnet build, pip install) — NOT a machine-global `pgrep` (which a shared dev box pins to "always building", permanently suppressing every stall). Shebang/interpreter wrappers are unwrapped one layer (`sh ./gradlew`, `env bash ./mvnw`, `python3 …/pytest`, `node …/jest`) so a wrapped build is matched on argv1/argv2, while a plain `node server.js` or `sleep` is not mistaken for one. The per-agent activity clock is the newest mtime under the agent's own worktree (`<worktrees>/agent-<name>`, incl. its own build dirs as liveness), else its `cwd` with `.git` pruned; a cwd shared by ≥2 occupants — counting the team-lead's own cwd (emitted as `LEADCWD` from the team config), so a de-isolated agent that lands in the lead's repo dir is caught — yields no per-agent signal (the lead's own file activity would otherwise keep the mtime fresh and mask the stall) and the member is flagged for an isolated worktree. Sources: **team** members (`isActive==true`, non-`team-lead`) and **worktree-isolated** agents (`<worktrees>/agent-*`) — both NAMED and task-gated, sharing one canonical label (leading `agent-` stripped); plus **background subagents** (`…/subagents/agent-*.jsonl`) — ANONYMOUS and **off by default** behind `--watch-subagents` (best-effort: a finished subagent has a stale transcript with no on-disk completion signal, and the harness already notifies on its completion/death). Missing-signal agents are SKIPPED, never defaulted to the Unix epoch (which would emit bogus ~56-year idle alerts); a STALLED agent that yields no evaluable signal for `--gone-polls` consecutive polls (default 2) is auto-cleared (`RESUMED … reason=gone`) and pruned — the consecutive-miss grace tolerates a transient one-poll config/`find` glitch instead of spuriously clearing the stall. Startup validates GNU `find`/`stat`, `python3`, and `resume_secs < stall_secs`. **Silent when healthy**: strictly edge-triggered, emitting only `STALL`/`RESUMED` transition lines to stdout (diagnostics to stderr). Verified live (member `bilby-2` owns an in_progress task but is actively working → zero output; per-agent build detection: a real `cargo`/`clippy` build elsewhere on the host does NOT suppress an idle owner, but a build under its own worktree does).

### Changed

- `grand-admiral` Worktree Isolation: broadened isolation-drop warning from team-spawns only to all code-mutating background agents. Confirmed second failure mode: standalone `run_in_background` agents also silently drop `isolation: "worktree"` and land in the main repo — two such agents switched its branch and left uncommitted edits, corrupting main. Added: in-prompt pwd self-checks are insufficient; lead pre-creation (pre-create worktree → inject absolute path → spawn WITHOUT the flag → agent `cd`s first) is the validated general approach for any code-mutating spawn.
- `grand-admiral` Token Economy model tiering + `dependabot-merge` Spawn Review Agents: added risk-based model tiebreaker — security-sensitive reviews (crypto, auth/key, network/transport, deserialization, untrusted input, large/opaque diffs) escalate to opus regardless of task type; routine low-risk reviews stay sonnet/haiku; when unsure, tier up for security, down for cost. `dependabot-merge` states the tiebreaker concretely: sonnet for routine bumps, opus for crypto/auth/network/parser/deserialization libraries or unusually large diffs.
- `git-and-github` Creating a PR + `coding-best-practices` present-state rule: PR descriptions now explicitly describe net final state only — no development history, changelog, or step-by-step iteration/debugging narrative (concise final `## Testing` results are allowed — they describe the final state, not history). `coding-best-practices` reconciled to match: historical context belongs in commit messages only (removed "PR descriptions" as a sanctioned destination for history).
- All crew agents (`architect-nagatha`, `developer-bilby`, `project-reviewer-adams`, `qa-engineer-marvin`, `security-engineer-smythe`, `technical-writer-trillian`, `ux-designer-diziet`) gain `SendMessage` in their `tools` frontmatter, giving background-spawned agents a reliable report channel (previously results were only recoverable from permission-gated transcripts). `architect-nagatha` also gains `Write`.
- Reconciled `isolation`-flag doctrine across workflow skills with the `grand-admiral` canonical section: `workflow-trivial`/`workflow-simplified`/`workflow-feature` now require the *outcome* (every code-mutating spawn works in an isolated worktree) instead of prescribing the unreliable `isolation: "worktree"` flag; `ci-dance` spawn and Isolation notes point to its pre-create workaround rather than the flag; `dependabot-merge` Spawn Review Agents pre-creates the worktree (the flag is silently dropped for `run_in_background` spawns) instead of passing it.
- `project-reviewer-adams` description no longer claims "Read-only" — it writes reports and delegates via `Task`. Now states it does not modify reviewed code (writes reports only), matching its `Write`/`Bash`/`Task` tool set.
- `agent-watchdog.sh`: a relative `--worktrees` root now resolves against the team-lead's cwd (`LEADCWD`) instead of the first member's cwd — a member may itself be running inside a worktree, making `<member-cwd>/.claude/worktrees` wrong and breaking worktree discovery; falls back to a member cwd only when the lead cwd is unknown. The header's Monitor-invocation example uses the portable `${CLAUDE_SKILL_DIR}/../../scripts/...` path (a bare relative `scripts/...` fails because the Monitor's CWD is the user's repo, not the plugin root).
- `grand-admiral` `## Recovery` doctrine fully rewritten. Harness death/completion remains the PRIMARY driver; the watchdog covers silently-stuck agents and spans team + worktree agents (NAMED, task-gated, with per-agent `/proc`-scoped build suppression and a per-agent worktree/cwd clock) plus opt-in background subagents (`--watch-subagents`, best-effort), framing a stall as **owning an in_progress task + idle + no build under that agent** and calling out that an idle agent with no assigned in_progress task is healthy and never flagged. Monitor one-liner uses the portable plugin-root path `${CLAUDE_SKILL_DIR}/../../scripts/agent-watchdog.sh` (resolves to the install location at skill-load time; the relative path would break since the Monitor's CWD is the user's repo). The watchdog's **silent-when-healthy / zero-token** property is stated. STALL event format documented (`reason=owns-in_progress-idle` for named, `reason=subagent-idle` for subagents). STALL-handling procedure (investigate-before-acting): inspect transcript + `git -C <cwd>` state, re-nudge a live-but-idle owner via `SendMessage`, or archive the inbox to `inboxes/<name>.json.killed-<ts>` and respawn the same agent-type on the SAME cwd/worktree with a context brief (transcript tail, `git log`, branch) and the SAME tasks re-fed via `TaskGet`, so committed progress survives. Escalate to user only after a second attempt fails. The allow-rule (`Bash(*/scripts/agent-watchdog.sh *)`) lives in settings, not skill frontmatter — an `allowed-tools` allowlist on this always-loaded coordinator skill would strip its other tools.

## [4.10.2] - 2026-06-16

### Changed

- `grand-admiral` Worktree Isolation: the team-spawn `isolation`-dropped block is restructured from a dense paragraph into a scannable bug+symptom statement followed by a numbered coordinator recipe (pre-create the worktree -> inject the absolute path into the spawn prompt -> instruct the agent to `cd` there first). Substance unchanged; the coordinator's action items are now explicit rather than buried.

## [4.10.1] - 2026-06-16

### Changed

- Removed references to the no-longer-available `fable` model. `grand-admiral` model-tiering rule now folds the former top-tier design work into the `opus` tier; `grumpy-review` per-invocation model example switched from "Fable" to "Sonnet" (a genuinely non-default model, since opus is already the default there). Released changelog history (4.7.0, 4.6.0) left intact as an accurate record.

## [4.10.0] - 2026-06-12

### Added

- New `bug-investigation` skill — root-cause discipline so reported bugs are diagnosed correctly by default: observation over theory; trace from the real entry point, not the well-named function; verify the exercised path; never conclude "not a bug" until the user's observation is reproduced. Born from a real 2026-06-12 failure (dash-evo-tool: a receive address derived past the SPV gap window → invisible funds, wrongly cleared as "not a bug").
- Preloaded on `qa-engineer-marvin`, `architect-nagatha`, and `developer-bilby` via `skills:`; referenced from `grand-admiral` (Agent Prompt Requirements, Skills Reference, Anti-Patterns).

## [4.9.0] - 2026-06-11

### Removed

- `discussions` toolset removed from `.claude-plugin/.mcp.json` `X-MCP-Toolsets` header. GitHub Discussions is disabled/unused on target repos, so its 5 tools were unused context overhead in every session.
- Orphaned discussion read tools (`get_discussion`, `get_discussion_comments`) removed from `tools` of `technical-writer-trillian` and `architect-nagatha`.
- All four discussion tools (`get_discussion`, `get_discussion_comments`, `list_discussions`, `list_discussion_categories`) removed from `tools` of `ux-designer-diziet`.

## [4.8.0] - 2026-06-10

### Fixed

- Severity reporting: two defects that let a report's machine-derived severities drift above the true picture. (1) **scope-inflation** — `scope` was routinely defaulted to `1.0` (observed: 27/28 findings), which floors the `mean(risk, impact, scope)` band at MEDIUM and over-counts HIGH/MEDIUM versus the real blast radius. (2) **dual-label drift** — reports carried machine floats AND a separately hand-typed prose severity label that, authored in parallel, disagreed with the floats.
- Fix A (derive-only labels): the renderer already derives every severity label from `risk`/`impact`/`scope` via `severity_util` (verified, unchanged); the `severity` skill and the producer skills now state explicitly that labels are DERIVED by the pipeline and MUST NOT be hand-typed in a companion document.
- Fix B (scope as blast radius): `claudius:severity` redefines `scope` as the actual blast radius (fraction of users / surface / call-sites reached) with a rating rubric (`1.0` repo-wide, `~0.5` subsystem, `~0.2` single call-site, `0.0` none) — it must be rated per finding, never left at `1.0`. `grumpy-review`, `review-pr`, `check-pr-comments`, and `triage-findings` cross-reference this (no duplicated rubric).
- Fix C (non-blocking consistency gate): `scripts/validate_report.py` now prints actionable `[consistency]` WARNINGS to stderr — a label/band mismatch when an explicit integer `severity` disagrees with the band recomputed from its floats, and an un-rated-axis smell when ≥80% of findings (≥5 findings) share one value in any of risk/impact/scope. The gate reuses `severity_util`'s banding and never fails validation (exit code stays 0 for otherwise-valid reports).
- The `mean(risk, impact, scope)` formula and band thresholds in `severity_util.py` were intentionally left unchanged — scope-weighting/capping is a deliberate future consideration (changing it would reband every existing report).

## [4.7.0] - 2026-06-10

### Changed

- All spawnable specialist agents (`architect-nagatha`, `developer-bilby`, `project-reviewer-adams`, `qa-engineer-marvin`, `security-engineer-smythe`, `ux-designer-diziet`, `technical-writer-trillian`) now default to `model: inherit` (previously opus or sonnet). The coordinator selects model per spawn. Driven by a 14-day analysis showing 97.6% of token cost ran on Opus, including mechanical spawns. The coordinator agent (`claudius`) intentionally stays `opus[1m]`.
- `grand-admiral` skill gains a **Token Economy** doctrine under `## Spawning`: three mandatory rules covering spawn discipline (inline small/sequential work by default — subagents were 70% of cost with 52% of spawns producing under 5k output), mandatory per-spawn model tiering (sonnet/haiku for mechanical work; opus only for deep analysis; and `fable` (top tier) for the architect's hardest design work), and read discipline (prefer Grep/Glob + offset/limit reads; delegate large fetches to a disposable sonnet subagent — Read was 60% of tool bytes). Existing "Model override" bullet and Anti-Pattern #7 updated to reference Token Economy rather than restate it.

## [4.6.0] - 2026-06-10

### Fixed

- `grumpy-review` and `review-pr` are no longer forked subagents (`context: fork` removed). A forked subagent cannot spawn nested agents, so the parallel reviewer fan-out in both skills silently degraded to a single self-run agent. Running inline restores the `Agent` spawn tool. Because `review-pr` §2 invokes `grumpy-review`, both had to lose `context: fork` so the fork-free chain propagates and spawn capability survives the nested invocation.
- `grumpy-review` no longer pins `model: opus` in frontmatter. On an inline skill that pin overrode the turn's model and suppressed per-invocation model requests (e.g. "review with Fable"); opus is now the in-body default that a per-review override can replace, so the requested model reaches every reviewer spawn.
- `grumpy-review` §4 gains an anti-degradation guard: for non-trivial reviews it confirms the `Agent` tool is available before fanning out and STOPs (rather than silently running a single self-review) if it is not — the trivial single-agent path is unaffected.

### Changed

- `grumpy-review` and `review-pr` `allowed-tools`: the spawn tool `Task` is renamed to `Agent` (its current name; `Task` was a legacy alias), and the inert `agent: claudius` frontmatter line (only meaningful with `context: fork`) is removed. The `TaskCreate`/`TaskUpdate`/`TaskList`/`TaskGet` task-list tools are unchanged.
- `ci-dance` Grumpy Stream: the "forked context" description of `/grumpy-review` is corrected to "runs inline and spawns its own reviewer agents" — wording only, no logic change.

## [4.5.0] - 2026-05-29

### Changed

- review-pr Pass C v1.1: compound PR titles are split on commas/em-dashes and each topic verified independently with a majority-hits rule; the "undocumented change" trigger keeps its ≥50-LOC threshold but now defines "mentioned" precisely (keyword overlap with ≥1 Summary bullet OR a field-ownership-table row); Summary-heading precedence is fixed as `## Summary` > `### Summary` > `## What changed` (first match wins, bullet-list fallback only when none match); Pass C may optionally set `finding_section.verdict` on its `pr_promises` section (PASS/FAIL/NEEDS_REVIEW) and `metadata.report_type: "pr_audit"` on the envelope.

### Fixed

- review-pr Pass C body extraction: a PR body wholly wrapped in a single code fence is now unwrapped and dedented before the column-0-anchored Summary/Out-of-scope regexes run, instead of silently matching nothing; if no Summary header and no top-level bullet list survive, Pass C emits one low-confidence LOW "PR body unparseable" finding rather than skipping silently.
- review-pr Pass C clean-pass output: a fully-clean Pass C now emits `findings: []` plus one INFO "PR self-description verified" finding, making a clean pass distinguishable from "Pass C did not run".
- review-pr Pass C code_snippets `language`: cross-references `claudius:report-format` §code_snippets for allowed `language` values instead of hard-coding `"diff"`.

## [4.4.0] - 2026-05-29

### Changed

- PR bodies now lead with a "Why this PR exists" rationale section (problem, reproduction/threat scenario, blocking relationship) before What/Testing/Breaking/Checklist. The skeleton lives in `skills/git-and-github/SKILL.md` (§Creating a PR); `skills/push/SKILL.md` delegates to it. Pinned by `tests/test_pr_body_template.py`.

## [4.3.0] - 2026-05-29

### Added

- Schema 3.1.0 (additive over 3.0.0; both validate): `metadata.report_type: pr_audit`, optional finding `author_type` (`bot`/`human`), optional `finding_section.verdict` (`PASS`/`FAIL`/`NEEDS_REVIEW`).
- Shared `scripts/severity_util.py` — single source of truth for the OWASP severity band table, per-finding severity derivation, and the summary-statistics / category-matrix builder, imported by both the coordinator (`consolidate_reports.py`) and the renderer (`generate_review_report.py`).

### Fixed

- check-pr-comments findings rendered INFO with zero severity counts — the renderer now derives per-finding severity from `risk`/`impact`/`scope` and recomputes summary statistics on-the-fly when absent or all-zero, so standalone producer reports show real severities and counts across Markdown / HTML / triage / PDF. A non-zero supplied `severity_counts` is never overwritten. The recompute also realigns `total_findings` so the HTML KPI can't disagree with the rebuilt counts.
- `consolidate_reports.ACCEPTED_SCHEMA_VERSIONS` is now derived from the schema's `schema_version` enum (single read) instead of a hard-coded set, so it can't drift on the next schema bump.
- Permalink commit now derives from `git rev-parse @{u}` (falling back to local `HEAD` only when the branch has no upstream) in `check-pr-comments`, `report-format`, and `grumpy-review`, so generated permalinks resolve on GitHub instead of 404-ing on an unpushed HEAD.

## [4.2.0] - 2026-05-28

### Added

- **Reviewer call-tree inspection**: `grumpy-review`, `review-pr`, and `check-pr-comments` now perform a deep transitive in-repo caller walk for every function modified by the diff. Reviewer probes the environment for the deepest analysis tool available (ctags, GNU global, ripgrep, tree-sitter) and falls back to grep-based caller extraction. Findings emit in new `call_tree` category with `CALL-` ID prefix. Walk is capped at depth 5, 200 callers, 60s per function; reviewer ranks modified functions by risk (public API > private; trait/interface impl > leaf; signature-changed > body-only) and walks the top 10 when a PR touches many.
- **Ephemeral-ID coding convention** in `skills/coding-best-practices/SKILL.md`: source code, comments, and committed docs MUST NOT reference transient review-finding IDs (e.g. `CMT-NNN`, `SEC-NNN`, `RUST-NNN`, `CALL-NNN`). Allow-list documented for permanent IDs (`ADR-NNN`, `RFC-NNN`, `CWE-NNN`, `CVE-YYYY-NNNN`, `OWASP-*`, GHSA, GitHub issue/PR refs, `TODO`/`FIXME`, committed test-spec IDs). Enforced two ways: Bilby (write-side, preloads BP) and `grumpy-review`/`review-pr` (review-side, via new `scripts/lint_ephemeral_ids.py`).
- **Schema**: `schemas/review-report.schema.json` extended with `call_tree` category and `CALL-` ID pattern (additive, no schema version bump).
- **Regression guards**: `tests/test_skill_frontmatter.py` parses every skill/agent frontmatter via PyYAML; `tests/test_bp_load_audit.py` asserts curated agent set loads `coding-best-practices`.

### Changed

- `coding-best-practices` skill is now loaded by every reviewer/coder agent (`architect-nagatha`, `claudius`, `developer-bilby` (already), `project-reviewer-adams` (already), `qa-engineer-marvin`, `security-engineer-smythe`, `technical-writer-trillian`, `ux-designer-diziet`) via YAML `skills:` frontmatter. Orchestrator skills that spawn coding/reviewing agents now explicitly require spawned agents preload BP (`grumpy-review` §3, `check-pr-comments` §3).

### Fixed

- `skills/release/SKILL.md`: YAML frontmatter `description:` value quoted to fix PyYAML parse error on unquoted colon. `claude plugin validate .` now exits 0 (previously reported this one error).

## [4.1.7] - 2026-05-27

### Changed

- `skills/check-pr-comments/SKILL.md`: producers MUST now emit `location_permalink` directly (lifted from the coordinator-owned exclusion list) whenever `metadata.project`, `metadata.commit`, and a line-addressable `location` (`path:line` or `path:start-end`) are all available. The skill documents the `https://github.com/{owner}/{repo}/blob/{commit}/{path}#L{n}[-L{m}]` template, range/single-line anchor handling, and URL-encoding requirements. Path-only `location` values are explicitly rejected to keep producer/coordinator parity — the coordinator's `_build_permalink` also rejects them. Fixes the `triage_server.py` rendering where standalone `check-pr-comments` reports showed `location` as plain text — the coordinator's derive pass never runs on producer-only output, so the producer is the only consistent place to populate the clickable permalink. Coordinator behaviour unchanged: when a consolidator pass does run it normalizes `location_permalink` from `metadata.repository` + `metadata.commit` + a line-addressable `location`; if any of those is missing, the existing producer value is preserved unchanged.
- `skills/check-pr-comments/SKILL.md`: tightened the `title` field contract. Titles are now bounded to 80 characters with NO trailing `...` truncation marker, MUST NOT prefix the reviewer username (the renderer already shows it separately), and MUST NOT verbatim-copy the comment's first line — Markdown markers (`**`, `>`), emoji, and severity labels (`Suggestion:`, `Issue:`, `Nit:`, `Question:`) from the comment body are stripped. Title phrases the change the comment requests as an imperative or noun phrase. Schema block now carries one positive example and three negative ones, lifted from a real PR #3554 report where titles read like quoted Markdown fragments.

### Added

- `tests/test_check_pr_comments_permalink.py`: regression coverage for the producer-side permalink template. Verifies the URL form for single-line (`#L42`) and range (`#L42-L56`) locations, owner/repo split from `metadata.project`, URL-encoding for unsafe path characters, graceful omission when commit, project, or parseable location is missing, and producer/coordinator parity on rejected edge cases (path-only, malformed range like `:1-` or `:-2`).

## [4.1.6] - 2026-05-27

### Changed

- `claudius:ci-dance` Step 2 and `claudius:grand-admiral` § Worktree Isolation: team-spawn quirk write-up now scoped to the one quirk that reproduces on the current harness — `Agent(team_name=..., isolation="worktree")` silently drops `isolation` and the agent lands in the lead's CWD instead of a dedicated worktree. Team-context inheritance is documented as an explanatory fact (`Agent()` calls from a team-lead session that OMIT `team_name` are auto-joined to the lead's team and lose `isolation` the same way — omitting `team_name` does not escape the team context). Single canonical workaround: the lead pre-creates one worktree per stream with `git worktree add .claude/worktrees/agent-<name> -b <branch> <SHA>` BEFORE spawning and includes the absolute path in each spawn `prompt`; each stream `cd`s into its assigned path on its first turn. The "spawn solo from within the team" alternative is no longer offered — team-context inheritance is why pre-create is the only stable path.

### Retracted

- Prior 4.1.3 assertion that `Agent(team_name=..., prompt=...)` silently ignores `prompt` (and that the lead must follow each spawn with a `SendMessage` kickoff to avoid deadlock) is **not reproducible** on the current Claude Code harness. Empirical re-validation: team-spawned agents receive their `prompt` and execute it on the first turn. The "kickoff" framing has been removed from both skills.

## [4.1.5] - 2026-05-27

### Fixed

- `scripts/generate_review_report.py`: all four v3 float-dimension chips (`overall_severity`, `risk`, `impact`, `scope`) in the HTML/Triage template now share the same `is number` guard. Previously only `impact` was guarded; the other three only checked `is not none`, so a producer/legacy report supplying any of them as a non-numeric value (e.g. a narrative string from a relaxed shape) would crash rendering with `TypeError: must be real number, not str`. Each chip is now rendered iff its underlying value is numeric, restoring per-field defensive parity with `_severity_tooltip`.

## [4.1.4] - 2026-05-27

### Changed

- `scripts/generate_review_report.py`: HTML and Triage renderers now surface v3 severity floats (`overall_severity`, `risk`, `impact`, `scope`) as visible monospace chips next to each finding's severity badge. Previously the floats were only readable via hover tooltip on the badge. Markdown and PDF renderers already showed them inline; this change brings HTML/Triage to parity. Renderer chips degrade gracefully on legacy reports where a float field carries a non-numeric value (e.g. `impact` as a narrative string from pre-v3 reports) — the affected chip is omitted, others render normally. Producer-shape reports under v3 still carry the required floats.

## [4.1.3] - 2026-05-27

### Fixed

- `scripts/generate_review_report.py`: triage view (`--format triage`) now actually renders the per-finding decision dropdown, rationale input, and decision hint that were silently missing since the v3 cutover. The post-hoc `.replace()`-based injection broke when `code_snippets` were inserted between `</dl>` and `</div>`; the renderer now uses Jinja `{% if triage %}` conditionals inside the template so the UI is wired structurally rather than by brittle string search. Adjacent `.replace()` calls in `render_triage` (extra CSS/JS blocks, `data-verdict` attribute, triage toolbar) audited; each now carries a post-replace assert to fail loudly if the anchor stops matching.

## [4.1.2] - 2026-05-27

### Changed

- `schemas/review-report.schema.json`: the v3 finding schema no longer requires coordinator-derived fields. Integer `severity` and float `overall_severity` are now optional alongside the already-optional `location_permalink` and AI verdict trio (`ai_assessment`, `ai_verdict`, `ai_verdict_confidence`). Producer-emitted reports validate without them; the coordinator's derive pass still WRITES them on consolidation. Resolves a contradiction where producer-only skills (e.g. `check-pr-comments`) couldn't validate their own output without first routing through `consolidate_reports.py assemble`. Producer-side fields (`id`, `risk`, `impact`, `scope`, `title`, `location`, `description`, `recommendation`) stay required — the schema still rejects findings missing any LLM-supplied judgement.
- `scripts/generate_review_report.py`: `sev_label` collapses missing / Jinja-undefined / non-int values to `"INFO"`, and the Markdown + PDF renderers read `severity` defensively (`.get("severity")`). Producer-shape reports — no integer `severity` yet — now render through all four renderers (Markdown, HTML, Triage, PDF) without crashing.
- `skills/report-format/SKILL.md`: example finding now carries a one-line note clarifying it is the producer-emitted shape and that the coordinator adds `severity` / `overall_severity` on its derive pass.
- `skills/validate-findings/SKILL.md`: description tightened to distinguish the typical "add AI fields, leave floats alone" run from the rare partial-producer case where the skill re-estimates absent `risk`/`impact`/`scope`.

## [4.1.1] - 2026-05-26

### Fixed

- `scripts/generate_review_report.py`: scoreboard tables in all four renderers (Markdown, HTML, Triage, PDF) now enumerate every category from the v3 schema instead of a hardcoded subset. Previously `pr_promises`, `pr_comments`, and `dependencies` rows were silently dropped from the severity x category matrix and from the Chart.js category bar chart. Driven by a single `CATEGORY_LABELS` map so future schema additions light up everywhere automatically.
- `scripts/generate_review_report.py`: triage HTML `data-category` attribute now reflects the finding's original section category, not the post-flatten wrapper. The flatten step previously stamped `data-category="all"` on every finding, breaking the triage category filter chip. Origin category is stashed on each finding (`_category`) before flattening; the template prefers it when present.
- `skills/review-pr/SKILL.md`: Pass C trigger hints now express severity as `risk≈X.Y, impact≈X.Y` float ranges (consistent with the v3 producer contract that emits floats and lets the coordinator derive integer bands) instead of the contradictory `→ HIGH/MEDIUM/LOW` labels.

### Changed

- `skills/report-format/SKILL.md`: the `pr_promises` example now includes a rationale paragraph explaining why each field carries its value (`scope: 1.0`, synthetic `location`, risk/impact rationale).

## [4.1.0] - 2026-05-26

### Added

- `skills/review-pr/SKILL.md`: new "Pass C — Promise Verification" audits the PR's self-description against the diff on three axes: title ↔ diff alignment, body Summary ↔ diff coverage, and out-of-scope enforcement. Reuses PR data fetched by §1, no extra MCP calls. Findings emit in v3 format with the new `pr_promises` category and `PPM-` ID prefix; `location` is a synthetic `PR-title` / `PR-body:summary-bullet-N` / `PR-body:out-of-scope-item-N` string (renderers leave it as plain text — no permalink).
- `schemas/review-report.schema.json`: `pr_promises` category added to the `finding_section.category` enum and `severity_category_matrix` row keys; `PPM-` prefix added to the `finding.id` regex. Additive only — pre-existing reports remain valid.
- `skills/report-format/SKILL.md`: `PPM-` row in the ID prefix table and a Pass C example demonstrating the synthetic `location` convention.
- `scripts/consolidate_reports.py`: `CATEGORY_PREFIX` map registers `pr_promises → PPM-` so the coordinator assigns IDs correctly for Pass C findings.
- `scripts/generate_review_report.py`: Markdown section heading ("Part VII: PR Promise Verification"), HTML/Triage filter chip option ("PR Promises"), and JS `catLabels` entry for `pr_promises`.
- `tests/fixtures/pr-promises/synthetic-mismatched.md`, `tests/fixtures/pr-promises/synthetic-clean.md`: synthetic PR title/body/diff fixtures for exercising Pass C — mismatched fixture expects 3 findings (one per axis), clean fixture expects zero.

## [4.0.3] - 2026-05-27

### Fixed

- `tests/test_report_pipeline.sh`: the fixture glob is now narrowed to `tests/fixtures/reports/v3-*.json`, so only v3 happy-path fixtures are exercised by the end-to-end pipeline. Previously the broad `*.json` glob swept in the negative-test `v2-legacy.json` (intended to fail v3 validation) and a stale pre-v3 fixture, causing CI to red on PR #35 after the v3 hard cutover.
- `tests/fixtures/legacy/v2-legacy.json`: relocated from `tests/fixtures/reports/` so it cannot be mistaken for an expected-pass fixture. The negative-rejection test in `tests/test_schema_v3_strict.py` follows the move.
- `tests/fixtures/reports/pr-13-severity-refactor.json`: removed as obsolete — it predated the v3 schema, had no test or script referencing it, and was only being kept alive by the pipeline glob.

## [4.0.2] - 2026-05-27

### Fixed

- `scripts/generate_review_report.py`: Markdown snippet `language` field is now sanitized via an allowlist (`[A-Za-z0-9_+.-]+`) before being interpolated into the GFM fence info-string; a producer-controlled value containing newlines or backticks can no longer break out of the fence and inject arbitrary Markdown/HTML downstream. Addresses Copilot review comment on PR #35.

### Changed

- `skills/report-format/SKILL.md`, `skills/grumpy-review/SKILL.md`, `skills/check-pr-comments/SKILL.md`: producer guidance now requires `risk`/`impact`/`scope` floats on every finding. Dropped the misleading "MAY emit integer `severity` alone" escape hatch — without all three floats the coordinator cannot derive `overall_severity` and the schema rejects the finding, so the previous wording contradicted the enforced contract. The `validate-findings` skill remains the documented path to populate floats post-hoc.

## [4.0.1] - 2026-05-26

### Fixed

- `scripts/generate_review_report.py`: HTML and Triage renderers no longer crash with `UndefinedError` when a finding carries `ai_verdict` without `ai_verdict_confidence` — the Jinja chip template now uses the `default(1.0, true)` filter, so a producer that emits only the verdict still renders.
- `scripts/generate_review_report.py`: `_verdict_color` no longer raises `ValueError` on `NaN`/`-Inf`/`+Inf` confidence values — `NaN` defaults to full saturation, infinities clamp to `[0, 1]`.
- `scripts/generate_review_report.py`: Markdown renderer skips the orphan "AI Assessment" label when `ai_assessment` is empty, emitting a compact `AI Verdict:` line instead.
- `scripts/generate_review_report.py`: Markdown code-snippet fences now grow longer than any backtick run inside the content, so a snippet that contains triple backticks no longer breaks out of the surrounding fence.
- `scripts/generate_review_report.py`: Markdown snippet `caption` is HTML-escaped before interpolation into `<summary>`, blocking HTML/Markdown injection from producer-controlled captions.
- `scripts/generate_review_report.py`: all four renderers (Markdown, HTML, Triage, PDF) validate `location_permalink` against `http(s)://` before emitting it as a clickable link — defense in depth against `javascript:` URIs.
- `scripts/consolidate_reports.py`: `_build_permalink` URL-encodes the path component (spaces, unicode, `#`, `?`) and rejects paths containing control characters, so permalinks no longer hijack the URL fragment or break across whitespace.
- `scripts/consolidate_reports.py`: `_GITHUB_REMOTE_RE` uses `\A`/`\Z` anchors with an explicit charset allowlist, so a remote URL with an embedded newline or whitespace no longer matches.
- `scripts/consolidate_reports.py`: `cmd_prepare` now detects v1/v2 envelope dicts carrying `schema_version` and rejects them with a version-aware error pointing at the v3 schema (previously the user saw a misleading "expected JSON array" message).
- `scripts/consolidate_reports.py` and `scripts/generate_review_report.py`: `jsonschema` validators are constructed with `format_checker=Draft202012Validator.FORMAT_CHECKER` so schema `format` clauses are enforced.
- `schemas/review-report.schema.json`: `location_permalink` (in both `top_findings` and `finding`) now also carries `pattern: "^https?://"`, hard-rejecting `javascript:` and other non-http(s) URIs even when the optional URI format checker is unavailable.

### Security

- `skills/validate-findings/SKILL.md`: added an "Adversarial content handling" section (OWASP LLM01) that instructs the validator to treat producer fields as quoted data, flag instruction-shaped overrides as evidence of badness, cap confidence on suspicious inputs, and tightened the `git show` allowlist glob from `Bash(git show *)` to `Bash(git show [0-9a-f]*)` to require a commit SHA prefix.

### Changed

- `skills/severity/SKILL.md`: clarified the OWASP normalization prose to match the formulas — the recipe is the arithmetic mean of factor scores divided by 9.0 (the previous "sum / 9.0" wording contradicted the `average` formula).
- `skills/grumpy-review/SKILL.md` and `skills/report-format/SKILL.md`: removed legacy "formerly known as" / "used to live in" framing from the `impact_description` field description; describe present-state only.
- `tests/fixtures/reports/v3-full.json`: corrected the copy-paste typo `lklimek_test` to `lklimek` so all permalinks in the fixture point at a consistent owner.

## [4.0.0] - 2026-05-26

### Added

- `schemas/review-report.schema.json`: multi-dimensional severity floats `risk`, `impact`, `scope` (0.0–1.0) plus derived `overall_severity` per the [OWASP Risk Rating Methodology](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology); CVSS v4.0-aligned band table maps `overall_severity` to integer `severity` 1..5.
- `schemas/review-report.schema.json`: `location_permalink` (GitHub `blob/<sha>/<path>#L<n>` URL) constructed by the coordinator from `metadata.commit` + `metadata.repository` + finding location.
- `schemas/review-report.schema.json`: optional `code_snippets[]` (`{language?, caption?, content}`) so producers can attach the exact source they inspected.
- `schemas/review-report.schema.json`: AI validation fields `ai_assessment` (Markdown), `ai_verdict` (`valid` | `false_positive` | `needs_investigation` | `out_of_scope` | `duplicate`), `ai_verdict_confidence` (0.0–1.0).
- `schemas/review-report.schema.json`: `metadata.repository` (`{owner, repo}`) auto-derived by the coordinator from `git remote get-url origin`; absent for non-GitHub / non-git directories.
- `skills/validate-findings/`: new coordinator-only skill that runs an opt-in LLM validation pass over a consolidated v3 report — populates `ai_assessment` / `ai_verdict` / `ai_verdict_confidence`, estimates missing OWASP float dimensions, and re-derives integer severity through the same Python helpers the coordinator uses.
- `skills/severity/SKILL.md`: "OWASP Risk Rating normalization" section with factor-averaging recipes for `risk` and `impact`, the 1.0 / 0.5 / 0.0 `scope` rubric, and the float→integer band table.

### Changed

- `schemas/review-report.schema.json`: `impact` is now a 0.0–1.0 float (the OWASP Impact dimension); the previous Markdown narrative is renamed to `impact_description` (still optional, still Markdown).
- `schemas/review-report.schema.json`: integer `severity` is now derived by the coordinator from the `risk`/`impact`/`scope` floats per the CVSS-aligned band table — producers may still emit it when they have no float estimate, but the coordinator overrides whenever floats are present.
- `schemas/review-report.schema.json`: `metadata.commit` must be a full 40-character SHA when present, so permalinks can be constructed unambiguously.
- Producer skills (`grumpy-review`, `check-pr-comments`, `review-pr`, `report-format`): JSON examples and emit rules updated for v3 — emit `risk`/`impact`/`scope` floats, optional `code_snippets`, full-SHA `metadata.commit`; do NOT emit coordinator/validator-owned fields.

### Removed

- `schemas/review-report.schema.json`: support for `schema_version` `1.0.0`, `1.1.0`, and `2.0.0`. Only `3.0.0` is accepted.

### Migration

v1/v2 reports are no longer accepted. Re-run the producer (grumpy-review / check-pr-comments / review-pr) against the current commit to regenerate findings against the v3 schema. There is no in-place conversion path.

## [3.14.5] - 2026-05-22

### Fixed

- `scripts/generate_review_report.py`: `CLAUDIUS_PDF_FONT` override now validates the `.ttf` extension before accepting a file, and the warning text is truthful about the actual condition — "is not a readable file" for a missing path, "is not a .ttf file" for a non-TrueType file (previously a non-TTF that existed was silently accepted while the warning still claimed "does not point to a TTF file").
- `scripts/generate_review_report.py`: `_resolve_font_set` docstring corrected — the `scripts/fonts/DejaVuSans*.ttf` slot is an optional user-supplied drop-in (not shipped with the plugin), and the override branch picks up `-Bold`/`-Oblique`/`-BoldOblique` siblings only (the monospace slot reuses the regular face; there is no `Mono.ttf` auto-pickup).
- `scripts/generate_review_report.py`: the Markdown -> ReportLab fallback warning now logs with `exc_info=True`, so the traceback (Markdown parse vs. BeautifulSoup vs. ReportLab mini-XML) is captured for diagnosis without changing the non-crashing behavior.

### Added

- `tests/test_generate_review_report.py`: pytest coverage for `_resolve_font_set` (env override valid/missing/non-TTF, sibling pickup, user-supplied dir, system-candidate fallback, no-font `None`) and `render_markdown_to_reportlab` (empty input, valid Markdown, malformed-input fallback to an escaped preformatted block with traceback logging). Fonts are isolated from the host so the suite is deterministic.

## [3.14.4] - 2026-05-22

### Fixed

- `scripts/generate_review_report.py`: the resolved Unicode TTF is now also wired into matplotlib (`font_manager.addfont` + `rcParams["font.sans-serif"]`) so PDF chart labels — e.g. agent names from `agent_stats` — render non-Latin scripts instead of tofu boxes, matching the ReportLab text flow. Best-effort: a matplotlib font failure logs a warning and leaves chart glyphs degraded but never aborts the render.
- `scripts/generate_review_report.py` / CHANGELOG: corrected the font-discovery wording. The `scripts/fonts/DejaVuSans.ttf` slot is an optional user-supplied drop-in, **not** a font shipped with the plugin; system fonts come from the `fonts-dejavu` / `fonts-noto` packages. Module docstring and 3.14.3 changelog entry updated to match.

## [3.14.3] - 2026-05-05

### Fixed

- `scripts/generate_review_report.py`: PDF output now registers a Unicode TrueType font (DejaVu Sans / Noto Sans, with bold/italic/mono siblings via `pdfmetrics.registerFontFamily`) so emoji and non-Latin scripts (Cyrillic, Arabic, Hebrew, etc.) render correctly instead of as tofu boxes. Discovery order: `$CLAUDIUS_PDF_FONT` env override -> optional user-supplied `scripts/fonts/DejaVuSans.ttf` (not shipped with the plugin) -> common Linux locations (`/usr/share/fonts/truetype/dejavu`, `/usr/share/fonts/truetype/noto`, provided by `fonts-dejavu` / `fonts-noto`). When no TTF is found the renderer logs a warning to stderr and falls back to ReportLab's Helvetica/Courier core fonts (Latin-1 only) -- never crashes.
- `scripts/generate_review_report.py`: `render_markdown_to_reportlab()` wraps the Markdown -> HTML -> ReportLab pass in try/except. On any failure (malformed input, parser exception, ReportLab mini-XML rejection) it logs a warning and falls back to a single XML-escaped preformatted block containing the raw source so no content is silently swallowed.

## [3.14.2] - 2026-05-05

### Fixed

- `scripts/gh-resolve-review-threads.sh`: REST/numeric `--id` values now resolve when they reference any comment in a thread, not just the head comment. The conversion query previously fetched `comments(first: 1)` per thread and matched only `comments[0].databaseId`, so a valid review-reply ID would fail with "could not map". The query now pulls `comments(first: 100)` and the jq selector scans every comment in the array.
- `scripts/gh-resolve-review-threads.sh`: `reviewThreads` is now paginated via `pageInfo { hasNextPage endCursor }`, so PRs with more than 100 threads no longer silently lose threads outside the first page. Capped defensively at 50 pages (5000 threads); exceeding the cap raises a clear error. The previous `TODO: paginate review threads beyond the first 100` comment is replaced with documentation of the new pagination behavior.

## [3.14.1] - 2026-05-05

### Added

- `scripts/gh-resolve-review-threads.sh`: enhanced mode now accepts `--id <thread_id>` (repeatable) so callers can target specific threads without filters. The flag accepts three formats — GraphQL node IDs (`PRRT_*` / `PR_kw*`), REST review-comment IDs (`discussion_r<n>`), and bare numeric `databaseId` — and auto-converts REST/numeric forms to thread node IDs by matching `databaseId` against the PR's review threads. Mixed formats in a single invocation are deduplicated and resolved in one batched GraphQL mutation. Closes the manual mapping step previously required when consuming `pull_request_read` MCP output.

### Changed

- `scripts/gh-resolve-review-threads.sh`: legacy mode now rejects non-GraphQL IDs with a clear error pointing the caller at the enhanced `--id` form (REST/numeric IDs cannot be converted without PR context). `PRRT_*` legacy invocations remain unchanged.

## [3.14.0] - 2026-04-30

### Added

- `scripts/generate_review_report.py`: HTML and PDF outputs render long-text finding fields (`description`, `impact`, `recommendation`, executive summary `summary_text`/`verdict_text`) as Markdown — bold, italic, headings (h1-h6 size-mapped in PDF), inline code, fenced code blocks, ordered/unordered lists, line breaks, and links. Markdown output (`--format md`) is unchanged (Markdown source passes through verbatim).
- `scripts/generate_review_report.py`: new helpers `render_markdown_to_html` (Jinja filter) and `render_markdown_to_reportlab` (BeautifulSoup tree walker emitting ReportLab mini-XML).
- HTML CSS: rules targeting Markdown rendered inside `<dd>` and `.exec-summary` (heading sizes, code/pre styling, list spacing).
- `scripts/requirements.txt`: declares `markdown >= 3.4` and `beautifulsoup4 >= 4.10` (plus the existing `jinja2`, `reportlab`, `jsonschema`).
- `skills/report-format`: new "Long-Text Field Format" section documenting Markdown as the default for `description`/`impact`/`recommendation`/executive summary fields.
- `schemas/review-report.schema.json`: long-text field `description` keywords now annotate the Markdown subset and reference the canonical renderer.

### Fixed

- `scripts/generate_review_report.py`: `**bold**`, `## headings`, `` `code` ``, lists, and line breaks no longer render as literal characters in HTML and PDF reports — multi-paragraph essays now show paragraph separation, headings, and inline formatting.

## [3.13.0] - 2026-04-29

### Added

- `coding-best-practices`: **present-state comments** rule — comments document what code does NOW and why; historical context belongs in commit messages and PR descriptions, not in code.
- `coding-best-practices`: **two-tier comment budget** — strict cap (≤2 lines preferred, 3 mediocre) for internal commentary and private rustdoc; relaxed (5–10 lines) for public API rustdoc that genuinely teaches downstream callers. Both tiers obey present-state.
- `coding-best-practices`: **verify-before-act** Cross-Cutting Rule — broad user instructions ("resolve all", "fix everything") express intent, not authorization to override observed reality. Verify actual state first; surface mismatches rather than silently fabricating completion.
- `check-pr-comments`: **verify-before-resolve** guardrail — before classifying any thread as resolved, verify the actual code state matches the reviewer's request. Threads that cannot be verified resolved are classified `Unresolved` with an explicit "needs verification" recommendation. Specific application of the `coding-best-practices` verify-before-act rule.
- All three workflow skills: **QA-phase parallel audits** via `qa-engineer-marvin` (READ-ONLY, no code edits):
  - *Docs review* — applies `coding-best-practices` comment rules (length cap + present-state + two-tier audience) to all comments and rustdoc introduced by the PR diff; emits findings with file:line citations and proposed rewrites.
  - *Dedup audit* — for every new public symbol, searches the workspace, direct dependencies, and project-defined reference repos for equivalent functionality; reports duplicates, overlaps, and reviewed-and-rejected items.
  - `workflow-trivial`: both audits may be skipped only when zero comment lines were added/modified (docs review) and zero new public symbols were introduced (dedup); both conditions must be documented.
- All three workflow skills: **implementation phase pre-empt directive** — Bilby must self-check comment rules and duplication before declaring impl done, and report any rejected equivalents with one-line rationale in the implementation summary so QA has context.

### Changed

- Worktree pre-flight default switched from blocking "STOP and push first" to a two-option pattern. **Option A (new default)**: capture local HEAD via `git rev-parse HEAD` and inject `git merge --ff-only <sha>` into every worktree agent prompt — no push required, because worktrees share the object store with the parent repo. **Option B (explicit fallback)**: push first; use only when origin is genuinely required (cross-machine work, PR-gated CI). Canonical doctrine in `grand-admiral` skill; mirrored in the Commit Discipline blocks of all three workflow skills.

## [3.12.0] - 2026-04-08

### Added

- `grand-admiral` skill: added "Candy Economy" section formalizing the incentive system — per-agent candy rules, coordinator validation, workflow tally
- `developer-bilby` agent: added Mindset section — earns candies for false positives reported by reviewers
- `architect-nagatha` agent: added Mindset section — earns candies for confirmed architecture findings
- `technical-writer-trillian` agent: added Mindset section — earns candies for confirmed doc gaps
- `ux-designer-diziet` agent: added Mindset section — earns candies for confirmed UX/accessibility issues

### Changed

- `grand-admiral` skill: removed inline "Candy tally" bullet from Output section (now covered by dedicated Candy Economy section)

## [3.11.2] - 2026-04-08

### Changed

- `grand-admiral` skill: updated Bilby and Marvin role descriptions in Crew Roster to clarify adversarial split — Bilby builds/fixes, Marvin proves code wrong (never fixes). Added "Bilby vs Marvin" note after the roster table

## [3.11.1] - 2026-04-08

### Added

- `grand-admiral` skill: added "Agent Reuse" subsection under Spawning — prefer `SendMessage` to running agents over spawning fresh ones for follow-up work in the same scope
- `grand-admiral` skill: added anti-pattern #10 — spawning fresh agents for follow-up work instead of reusing via SendMessage

## [3.11.0] - 2026-04-08

### Added

- `grand-admiral` skill: extracted multi-agent orchestration doctrine from `claudius` agent — spawning, worktree isolation, team coordination, scaling, recovery, anti-patterns, programme management, planning, crew roster, and skills reference

### Changed

- `claudius` agent: slimmed to personality + session protocol only; all orchestration knowledge now loaded via `grand-admiral` skill. Reduces agent prompt size by ~65%, improving context compaction resilience

## [3.10.0] - 2026-03-27

### Changed

- All workflows (`workflow-feature`, `workflow-simplified`, `workflow-trivial`): restructured to mandatory 4-phase order — Planning → Implementation → QA → Lessons Learned. Phases cannot be skipped, merged, or reordered; tasks within a phase may be combined
- `workflow-feature` Planning phase: 4 sub-phases (Requirements → UX Design → Test Case Specification → Development Plan), each producing an artifact for the next
- Test Case Specification moved from Implementation to Planning — specs (not code) written before implementation begins
- All workflows: added Failure & Auto-Retry — phase failure auto-returns to previous phase without user wait (unless decision needed), max 3 retries
- All workflows: added unattended operation mode — no pauses between phases, single Final Report at the end
- `ci-dance`: made EXIT SUCCESS condition explicit about all three streams (CI, Grumpy, Review)
- `claudius` agent: task list usage now mandatory for ALL work, not just team coordination


## [3.9.0] - 2026-03-25

### Added

- `claudius` agent: expanded Spawning section with team coordination docs — decision framework, lifecycle, task list patterns, SendMessage patterns, and example
- `workflow-feature`: added Multi-Agent Coordination section for team-based phases

## [3.8.2] - 2026-03-25

### Fixed

- `ci-dance`: main loop exits after 1 iteration instead of continuing — added explicit state initialization, mandatory continuation guard, iteration logging, and fresh-results emphasis per iteration

## [3.8.1] - 2026-03-24

### Added

- `coding-best-practices`: added `## Logging Levels` section — quick-reference table for error/warn/info/debug/trace with Rust `tracing` crate requirement
- `rust-best-practices`: updated Logging entry to reference `coding-best-practices § Logging Levels` and enforce `tracing` over `log`

## [3.8.0] - 2026-03-24

### Changed

- `ci-dance`: redesigned as parallel review pipeline — CI, copilot, and local `/grumpy-review` run concurrently instead of sequentially
- `ci-dance`: removed `claudius-review` label dependency — grumpy-review runs locally in the session, no GitHub label needed
- `ci-dance`: added consolidation step that merges findings from grumpy-review, copilot, and CI into a unified view
- `ci-dance`: added validation/classification gate — verify findings exist in current code and are real before fixing
- `ci-dance`: timeout increased to 300 minutes (configurable via `timeout=N` argument)
- `ci-dance`: copilot wait window reduced to 5–20 min (was 15–45 min) — copilot reviews are fast
- `ci-dance`: removed `Bash(gh label *)` from allowed-tools
- `ci-dance`: merged `ci-loop` skill inline — CI monitoring logic now lives directly in ci-dance, `ci-loop` removed

## [3.7.0] - 2026-03-23

### Changed

- `check-pr-comments`: differentiated resolution logic based on author type (bot vs human) and fix status. Bot threads that are fixed are auto-resolved; all other categories receive a reply comment. Human threads are never auto-resolved unless the user gives explicit per-invocation permission. Added `author_type` field to finding JSON schema. Added `mcp__plugin_claudius_github__add_issue_comment` to allowed tools for PR-level comment replies.
- `ci-dance` skill: rewritten as fully unattended coordinator loop — no confirmations, push freely, 60-min hard timeout
- `ci-dance`: severity filtering — only fix MEDIUM+ bot review findings, skip LOW/INFO to avoid wasted CI round-trips
- `ci-dance`: 10-min minimum review wait (was 30-min), 15-min max wait
- `ci-dance`: expanded `allowed-tools` with `gh run *`, review scripts, and MCP tools for full autonomy
- `ci-dance`: explicit sub-skill confirmation override in unattended mode
- `ci-dance`: review wait 15–45 min (was 10–15 min), total timeout 120 min (was 60 min) — calibrated from dashpay/dash-evo-tool Claudius review data (median 29 min)

## [3.6.4] - 2026-03-19

### Fixed

- `gh-resolve-review-threads.sh`: `((i++))` evaluated to false (exit code 1) when `i=0`, causing `set -e` to kill the script on the first thread. Changed to `((i++)) || true`.

### Added

- `git-and-github` skill: guidance on formatting multi-line PR bodies with GitHub MCP tools — use real newlines, not `\n` escape sequences.


## [3.6.3] - 2026-03-19

### Changed

- Agent voice directives: replaced generic "Communication Style" sections with character-specific Voice rules ensuring each agent writes in their personality across all output (PR comments, review findings, reports, GitHub comments)
- Adams feedback guidelines rewritten to match his no-nonsense character while preserving conventional comment prefixes

## [3.6.2] - 2026-03-18

### Fixed

- Added ERR trap to all 7 `gh-*.sh` wrapper scripts for diagnosable failure messages with file and line context
- Safety rule #10: `gh`/`ghsudo` sandbox guidance — recommend `sandbox.network.allowedDomains: ["api.github.com"]` over `dangerouslyDisableSandbox`. Troubleshooting entry added to `gh-cli-fallback.md`
- Safety rule: never fork repositories on access denied — use `ghsudo` or ask user (`git-and-github` skill + `gh-cli-fallback.md`)

### Changed

- `gh-request-reviewer.sh` rewritten: uses `gh pr edit --add-reviewer` for all reviewer types (users, bots, `@copilot`), supports multiple reviewers, removed REST API and ghsudo wrapper
- `@copilot` reviewer syntax and `gh` ≥ 2.88.0 requirement centralized in `git-and-github` skill (§ Requesting Reviewers)
- `ci-dance` and `review-loop` reference `git-and-github` instead of inline version notes
- `review-loop` now requires `git-and-github` skill in prerequisites

## [3.6.0] - 2026-03-18

### Changed

- Agents renamed to role-name format: `architect` → `architect-nagatha`, `project-reviewer` → `project-reviewer-adams`, `qa-engineer` → `qa-engineer-marvin`, `security-engineer` → `security-engineer-smythe`, `technical-writer` → `technical-writer-trillian`, `ux-designer` → `ux-designer-diziet`
- Character names removed from agent `description` fields (now part of agent ID)
- SETUP.md agent table: dropped Character column (names now in agent IDs)
- All cross-references updated across agents, skills, and docs

### Added

- README.md: Reading List section with SF source material

## [3.5.0] - 2026-03-18

### Added

- `ci-dance` skill: end-to-end PR pipeline — push → CI green → review → fix comments → repeat until approved or timeout
- `push` skill: commit, push, and create/update PR in one command
- `SETUP.md` — detailed setup guide (agents, MCP, ghsudo, permissions, skill catalog, eval data)

### Changed

- `README.md` rewritten as a sales pitch in Claudius storytelling voice — summary table, three featured skills, compact installation with dependency list
- All agents get SF character names and personalities: Nagatha (architect-nagatha), Adams (project-reviewer-adams), Bilby (developer-bilby), Smythe (security-engineer-smythe), Marvin (qa-engineer-marvin), Trillian (technical-writer-trillian), Diziet (ux-designer-diziet)
- Agents renamed to role-name format (e.g., `architect` → `architect-nagatha`); character names now part of agent ID
- `ux-designer-diziet` agent promoted to opus model

## [3.4.4] - 2026-03-18

### Changed

- `ci-dance` skill: full rewrite to production quality — imperative instructions, explicit pipeline loop (push → ci-loop → request reviews → wait → check-pr-comments → fix → repeat), prerequisites, exit conditions, final report, `allowed-tools` frontmatter, no-confirmation policy, fixed typo (`check-ci-comments` → `check-pr-comments`), corrected duplicate step numbering

## [3.4.3] - 2026-03-17

### Changed

- `references/source-of-truth.md` — condensed ~34% (630→415 words): merged redundant NEVER table rows, dropped Fallback column, removed "Never Store" section (covered by Bad examples), shortened headers

## [3.4.2] - 2026-03-17

### Fixed

- `claudius` agent: replace unresolvable `references/source-of-truth.md` file path with reference to hook-injected Source of Truth content (agents have no variable substitution)
- `session-start` hook: use `hookSpecificOutput.additionalContext` instead of `systemMessage` — the latter only shows user-facing warnings, never enters Claude's context

## [3.4.1] - 2026-03-17

### Fixed

- `lessons-learned` skill: deduplicate Quality Gate section — replaced inline criteria and examples with pointer to `references/source-of-truth.md`
- `lessons-learned` skill: improve description to third-person trigger-phrase form
- `hooks/hooks.json` SessionStart: replace unsupported `type: "prompt"` hook with `type: "command"` hook (SessionStart only supports command hooks per Claude Code docs); add `hooks/session-start.sh`

## [3.4.0] - 2026-03-17

### Added

- `lessons-learned` skill — moved from memcan plugin; claudius now owns classification logic for what to save
- `references/source-of-truth.md` — knowledge source priority map (created by parallel agent)
- SessionStart hook — searches persistent memory for project context on session start

### Changed

- All agents: use `claudius:lessons-learned` instead of `memcan:lessons-learned`
- All agents: add quality reminder — skip lessons-learned for routine sessions
- Workflow skills: reference `claudius:lessons-learned`

## [3.3.1] - 2026-03-17

### Changed

- `check-pr-comments` — step 4 now requires Claude's per-comment assessment: adequacy verdict for resolved comments, priority recommendation for unresolved ones, and explicit disagreement with reviewer when warranted

## [3.3.0] - 2026-03-17

### Changed

- Mandate worktree isolation for ALL spawned agents, not just parallel ones
- Make worktree pre-flight check blocking — STOP and push before launching agents if unpushed commits exist
- Task batching guidance: merge small tasks so each agent gets ≥100 lines of work within same specialization
- Update CLAUDE.md bundled file references convention to document `${CLAUDE_SKILL_DIR}` and clarify `${CLAUDE_PLUGIN_ROOT}` scope

### Fixed

- Replace broken `../../scripts/` relative paths with `${CLAUDE_SKILL_DIR}/../../scripts/` in all skills and reference docs — fixes script-not-found errors when agents run in worktrees or project directories
- Use path-agnostic globs in `allowed-tools` frontmatter for reliable tool permission matching

## [3.2.11] - 2026-03-17

### Fixed

- `security-engineer`, `project-reviewer` — added Write tool to agent definitions so they can write findings JSON directly instead of resorting to Bash commands (python3, tee, cat redirect) which are blocked by CI tool allowlists
- `report-format` — added File Output section instructing all agents to use Write tool for file creation, not Bash commands

## [3.2.10] - 2026-03-16

### Changed

- `developer-bilby` — added codebase consistency instruction: study existing patterns (design, naming, error handling, idioms) before writing new code; added "mental model" principle as workflow intro

## [3.2.9] - 2026-03-16

### Changed

- `git-and-github` — added pre-work checks: verify on base branch before starting new work, search open PRs for existing fixes, search open+closed issues before creating new ones (ask user if duplicate found)


## [3.2.8] - 2026-03-15

### Changed

- `rust-best-practices` — added Cargo Command Hygiene rules: (1) replace `cargo check` with `cargo clippy` everywhere, (2) never pre-compile before `build`/`clippy`/`test`, (3) capture full cargo output instead of re-running with different truncation. Based on analysis of 1,082 redundant cargo executions across 2 days.

## [3.2.7] - 2026-03-14

### Changed

- Worktree instructions: require resolved commit SHA (from `git rev-parse HEAD`), explicitly prohibit branch names or symbolic refs — refs resolve differently inside worktrees

## [3.2.6] - 2026-03-14

### Changed

- `rust-best-practices` — added dedicated Error Handling section: `thiserror` with typed enums only (no `anyhow`/`eyre`), `Display`/`Debug` separation, granular variants over generic strings, `#[from]`/`#[source]` patterns, anti-patterns list. Inspired by dash-evo-tool conventions.

## [3.2.5] - 2026-03-14

### Changed

- Worktree orchestration: inject base commit hash (`git merge --ff-only <hash>`) into worktree agent prompts so they sync to correct local HEAD instead of stale origin

## [3.2.4] - 2026-03-13

### Changed

- Worktree orchestration: always push to remote after merging worktree agent work into main (prevents stale-origin for subsequent waves)

## [3.2.3] - 2026-03-13

### Added

- `git-and-github` — Context Management section: delegate large MCP responses (diffs, file lists, review threads, CI logs) to disposable subagents to avoid context pollution

### Changed

- `grumpy-review`, `check-pr-comments` — replaced ad-hoc CI log retrieval guidance with cross-reference to centralized `git-and-github` § Context Management
- `review-pr` — added large-response warning for `get_files`/`get_diff` with subagent pattern reference
- `git-and-github/references/pr-review.md` — added large-response note in Get PR Context section

## [3.2.2] - 2026-03-13

### Changed

- `grumpy-review` — removed `Bash(cat ../../schemas/*)` from `allowed-tools` (agents use Read tool; `cat` inside `$(...)` command substitution doesn't need its own permission)

## [3.2.1] - 2026-03-13

### Changed

- `grumpy-review` — report output uses `${REPORT_DIR:-.}/report.json` instead of relative `report.json` (fixes CI artifact upload failures)
- `grumpy-review` — added `Bash(mkdir *)` to `allowed-tools` (fixes permission denial in fork context)
- `grumpy-review` — agent prompt requirements now include CI context constraints (MemCan/WebSearch unavailability) and file output rules (Write tool, not cat heredocs)
- `grumpy-review`, `check-pr-comments` — added CI Log Retrieval section: `get_job_logs` with `return_content: false` to avoid context bloat
- `claudius` agent — temp dir pattern changed from `/tmp/claude/XXXXXX` to `/tmp/claudius-XXXXXX` (avoids compound-command permission denials)
- `claudius` agent — Skills Reference: added `dependabot-merge`, clarified `lessons-learned` as memcan plugin skill
- `settings.example.json` — added `consolidate_reports.py`, `jq`, `/tmp/claudius-*` cleanup permissions

### Fixed

- CI review workflow (`dash-evo-tool`): added 10 missing shell script permissions to `--allowedTools`, removed `Bash(grep *)` (agents should use Grep tool), added `jq`, documented `issues: write` rationale

## [3.2.0] - 2026-03-12

### Added

- `skills/git-and-github/references/pr-review.md` — dedicated PR review reference (MCP-first, CLI fallback) covering context fetch, deduplication, diff-bounds verification, and draft review posting with wrapper scripts
- Candy tally system: `qa-engineer`, `security-engineer`, and `project-reviewer` each report a 🍬 count (findings by severity) at the end of their reports
- `claudius` collects and presents per-agent candy tallies at workflow wrap-up; most findings wins bragging rights

### Changed

- `qa-engineer` — explicitly forbidden from fixing production code; findings are successes
- `git-and-github/references/gh-cli-fallback.md` — PR review section collapsed to a pointer; `git-and-github/SKILL.md` ghsudo section collapsed to a one-liner (detail lives in references)
- `review-pr/SKILL.md` — detailed git/GitHub posting instructions removed, replaced with reference to `pr-review.md`

### Added (3.1.1)

- `rust-best-practices` — build optimization guidance (LTO, codegen-units, strip, opt-level)

## [3.1.0] - 2026-03-12

### Added

- Per-language security pattern references: `python-security-patterns.md`, `rust-security-patterns.md`, `go-security-patterns.md`, `typescript-security-patterns.md` — web-researched attack patterns with CVE citations, replacing monolithic `language-security-patterns.md`
- Language-specific security scanner tables in each pattern file
- Pattern index table in `security-best-practices` SKILL.md for discoverability

### Removed

- `language-security-patterns.md` — split into per-language files to reduce context loading

## [3.0.0] - 2026-03-12

### Removed

- **business-domain-analyst** agent — merged into `ux-designer`
- **devops-engineer** agent — responsibilities absorbed by `developer-bilby`, `project-reviewer`, `architect`, and `security-engineer`

### Changed

- **ux-designer** now covers requirements & domain analysis (personas, user stories, stakeholder mapping, prioritization)
- **qa-engineer** rewritten as adversarial requirements validator — prove code doesn't match specs, structured finding reports (QA-NNN)
- **technical-writer** default model changed from opus to sonnet
- **claudius** spawning rules now include explicit model override guidance (sonnet for routine, opus for deep analysis)
- **architect** owns deployment model planning (previously shared with devops-engineer)
- Added Model Selection section to all three workflow skills (trivial, simplified, feature)
- Fixed stale `frontend-design` skill reference in ux-designer

## [2.3.1] - 2026-03-12

### Added

- Unified `mcp__plugin_memcan_brain__search` tool to all 9 agents with explicit tool lists — enables single-call search across all MemCan collections

## [2.3.0] - 2026-03-11

### Added

- `merge-base`: upstream attribution section — identifies authors whose changes caused conflicts or semantic issues, with linked PRs

## [2.2.0] - 2026-03-11

### Added

- `dependabot-merge` skill — bulk-process open dependabot PRs: audit each dependency via `review-dependency`, post findings as comments, squash-merge if CI green, request rebase on conflicts or CI failures with watch loop (poll until rebase lands, then merge or report). User-invocable.

## [2.1.0] - 2026-03-11

### Added

- `release` skill — universal release workflow that auto-detects project tech stack (Rust, Python, JS/TS, Claude Code plugins), validates version consistency across all version files, bumps version, updates changelog, commits, pushes, and creates GitHub release. User-invocable only (`disable-model-invocation: true`).

## [2.0.0] - 2026-03-11

### Changed

- **BREAKING**: GitHub MCP server is now a hard dependency — skills and agents require `https://api.githubcopilot.com/mcp/` with `GH_TOKEN` configured. `gh` CLI demoted to fallback (see `references/gh-cli-fallback.md` in affected skills).
- `check-pr-comments`: JSON report is now optional (only on explicit request); default flow presents concise inline summary
- `check-pr-comments`: always fetch fresh comments from GitHub — never assume cached or absent
- `git-and-github`: added Changelog section enforcing Keep a Changelog format

## [1.16.2] - 2026-03-11

### Fixed

- `block-github-writes` hook: match both bare (`claudius`) and qualified (`claudius:claudius`) agent_type so coordinator isn't blocked by its own hook

## [1.16.1] - 2026-03-10

### Fixed

- `check-pr-comments`: replaced generic `Bash(*gh-*.sh *)` with specific per-script allowed-tools
- Added CLAUDE.md convention: `allowed-tools` Bash globs must match exact script names, not generic patterns

## [1.16.0] - 2026-03-10

### Changed

- `check-pr-comments` skill now MCP-first: uses `pull_request_read` for fetching comments, reviews, and threads; gh CLI moved to `references/gh-cli-fallback.md`
- `check-pr-comments` narrowed `allowed-tools`: `Bash(gh pr *)` → `Bash(gh pr checkout *)`, added MCP tools
- `grumpy-review` skill: added trivial review tier (< 200 lines, single agent) — skips consolidation pipeline
- `grumpy-review` skill: collapsed redundant security-engineer instances into single agent with expanded scope

## [1.15.0] - 2026-03-10

### Changed

- `git-and-github` skill now MCP-first: prefers GitHub MCP tools for all API operations
- Moved all `gh` CLI commands, wrapper script docs, and troubleshooting to `references/gh-cli-fallback.md` (loaded only when MCP unavailable)
- Skill ~40% smaller — rules, guidance, and attribution remain; tooling details deferred to fallback

## [1.14.2] - 2026-03-10

### Fixed

- MCP config `Authorization` header used unsupported bash default-value syntax `${GH_TOKEN:-${GITHUB_TOKEN}}` — simplified to `${GH_TOKEN}`
- Removed `GITHUB_TOKEN` fallback references from README (MCP config only supports simple `${VAR}` substitution)

## [1.14.0] - 2026-03-10

### Added

- GitHub MCP server (remote HTTP) via `https://api.githubcopilot.com/mcp/` — centralized in `.mcp.json`
- All agents inherit GitHub MCP from plugin-level config (readonly, all toolsets)
- `claudius` gets inline read-write override with scoped toolsets
- PAT auth via `GH_TOKEN` env var — no auth duplication in agent frontmatter
- README setup guide with fine-grained PAT permissions table

### Changed

- `ghsudo` demoted from primary to optional fallback in `git-and-github` skill
- Helper scripts (`gh-post-review.sh`, `gh-request-reviewer.sh`, `gh-resolve-review-threads.sh`) now try `gh` directly, fall back to `ghsudo` on 403/404
- README ghsudo section reframed as optional

## [1.13.2] - 2026-03-09

### Changed
- Compress claudius orchestrator agent prompt (~44% reduction) — same semantics, fewer tokens

## [1.13.1] - 2026-03-09

### Changed
- Rename `gh-resolve-review-thread.sh` → `gh-resolve-review-threads.sh` (plural) — now accepts multiple thread IDs
- Batch all thread resolutions into a single GraphQL call using aliased mutations (one `ghsudo` invocation)
- Update references in `settings.example.json`, `git-and-github` skill, and `triage-findings` skill

## [1.13.0] - 2026-03-09

### Added

- MemCan MCP server integration in all agent frontmatter — agents can now search and store persistent memories across sessions
- MemCan search tools (search_memories, search_code, search_standards) for all agents
- MemCan write tool (add_memory) for all agents with explicit tool lists; claudius orchestrator inherits all tools
- MemCan context injection guidance in orchestrator agent prompt
- All agents instructed to invoke `memcan:lessons-learned` before finishing to persist session learnings

## [1.12.0] - 2026-03-08

### Changed
- Worktree isolation is now a coordinator decision at spawn time, not an agent default — use only for parallel agents
- Remove `isolation: worktree` from agent frontmatter (developer-bilby, qa-engineer, devops-engineer, technical-writer)
- Replace verbose "Worktree Discipline" sections in agents and coding-best-practices with lightweight "Commit Discipline"
- Rewrite coordinator "Worktree Lifecycle" as "Worktree Isolation" — parallel-only policy with same safety checks
- Simplify "Worktree & Commit Discipline" in all workflow skills (feature, simplified, trivial) to "Commit Discipline"

## [1.11.2] - 2026-03-08

### Changed
- Require architect agent to WebSearch latest crate/package versions before recommending dependencies
- Add "Verify dependency versions" rule to coding-best-practices skill

## [1.11.1] - 2026-03-08

### Changed
- Add unpushed-commit pre-flight check to claudius coordinator (Worktree Lifecycle) and all three workflow skills (workflow-feature, workflow-simplified, workflow-trivial)
- Add startup stale-origin detection to all worktree agents (developer-bilby, qa-engineer, devops-engineer, technical-writer) and coding-best-practices skill

## [1.11.0] - 2026-03-08

### Changed
- Replace TDD methodology in qa-engineer agent with black-box testing approach: define expected behavior from documentation and requirements (never source code), write tests from expectations, treat any deviation as a bug

## [1.10.1] - 2026-03-06

### Changed
- Add stale-worktree divergence warning to developer-bilby, qa-engineer, technical-writer, and devops-engineer agents
- Add tight-coupling anti-pattern to claudius agent delegation guidelines
- Add "Before You Start" memory-check step to workflow-feature, workflow-simplified, and workflow-trivial skills
- Add "Change visibility" guidance (git diff + git status) to claudius agent prompt requirements
- Add MemCan Integration section to technical-writer, business-domain-analyst, ux-designer, devops-engineer

### Fixed
- Schema ID prefix regex now accepts CODE- and DEP- prefixes generated by consolidate_reports.py

## [1.10.0] - 2026-03-06

### Changed
- Replace removed MemCan skill references (`search-code`, `search-standards`, `list-collections`) with direct MCP tool references for MemCan 0.18.0

## [1.9.8] - 2026-03-06

### Changed
- Update MemCan skill references for v0.17.0: add `lessons-learned` and `list-collections` to claudius agent, add `list-collections` hints to architect, security-engineer, developer-bilby, and security-best-practices

## [1.9.7] - 2026-03-06

### Changed
- Add MemCan search skill references (`memcan:recall`, `memcan:search-code`, `memcan:search-standards`) to agents and skills as optional integrations

## [1.9.6] - 2026-03-06

### Changed
- Add sunk-cost rule to claudius agent: always do what is correct, even if it means redoing previous work

## [1.9.5] - 2026-03-06

### Changed
- Add UX/DX awareness to severity, grumpy-review, triage-findings, check-pr-comments, and coding-best-practices skills — agents now consider end-user and developer experience impact alongside technical correctness

## [1.9.4] - 2026-03-06

### Fixed
- All agents now use `model: opus` instead of `model: inherit` — `inherit` fails with "model not found" error when agents run as team members

## [1.9.3] - 2026-03-05

### Changed
- Worktree discipline across all agents now requires mandatory commit before exiting — never leave uncommitted work
- Agents must only commit to their worktree branch, never to main/master
- Claudius coordinator worktree lifecycle expanded with post-wave verification checklist (status, log, merge, then cleanup)
- Workflow skills (feature, simplified, trivial) now include worktree & commit discipline section with verification steps
- `developer-bilby` agent now has explicit worktree discipline section (was missing despite `isolation: worktree` in frontmatter)
- `coding-best-practices` skill worktree section updated to match new discipline

## [1.9.2] - 2026-03-05

### Fixed
- Schema finding fields (`title`, `location`, `description`, `recommendation`) now enforce `minLength: 1` — was documented in 1.9.1 changelog but missing from schema due to lost worktree merge

## [1.9.1] - 2026-03-05

### Changed
- Schema finding ID pattern now accepts `CODE-` and `DEP-` prefixes (was blocking report output)
- Schema required string fields (`title`, `location`, `description`, `recommendation`) enforce `minLength: 1`
- `_flatten_agent_report` skips findings with empty required fields (aligned with schema)
- `_flatten_agent_report` validates severity is a known enum value and location is a string
- Schema validation returns error (not silent pass) when schema file is missing
- `jsonschema` imported at module level with clear error message if missing
- Extracted `_load_json_file()` helper to eliminate duplicated file-loading boilerplate
- Extracted `_iter_findings()` generator for consistent section/finding iteration
- `assign_ids()` mutates in-place, returns None (was hybrid mutate-and-return)
- `similarity_score` normalized to 0.0–1.0 range (was unbounded sum up to 3.0)
- `scan_intentional` uses pure Python file reading instead of subprocess grep
- `generate_remediation` logs warning for unknown severity values
- Standardized None/empty value cleanup via `_strip_none_values` helper
- Changelog [1.9.0] "Fixed" items moved to "Changed" (design decisions, not bug fixes)
- INTENTIONAL annotation added for schema matrix not requiring dependencies column

### Added
- `TestFlattenAgentReport` test class (7 tests for field extraction, validation, edge cases)
- `test_matrix_cell_values` — asserts specific counts in severity-category matrix
- `test_empty_title_skipped` — verifies empty required fields are rejected

### Fixed
- Unused `make_finding` parameter removed from `make_section` test fixture

## [1.9.0] - 2026-03-05

### Added
- `scripts/consolidate_reports.py` — two-phase report consolidation for parallel agent reviews (prepare + assemble)
- Unit tests for consolidation script (`tests/test_consolidate_reports.py`, 59 tests)
- `dependencies` column in schema severity-category matrix (`review-report.schema.json`)

### Changed
- `grumpy-review` skill rewritten to use consolidation script instead of manual multi-step process
- Schema validation now gates report output — invalid reports are not written (exit code 1)
- `jsonschema` is now a hard requirement for the consolidation script
- Code quality prefix fallback changed from `RUST-` to `CODE-` for language-neutral reviews
- `$TMPDIR` references in skill examples now use `${TMPDIR:-/tmp}` fallback
- Path traversal protection in `scan_intentional` — file paths resolved and checked against repo root
- `assign_ids()` mutates in-place and returns None
- `generate_remediation()` excludes INFO findings from action buckets
- Unknown severity values handled safely in sorting (dict lookup with default)
- 8 MB input file size limit to prevent resource exhaustion
- Output directories created automatically if they don't exist

## [1.8.3] - 2026-03-04

### Changed
- All `gh-*.sh` scripts now accept `owner/repo` as a single argument instead of separate `<owner>` and `<repo>` args
- Updated usage examples in `git-and-github` and `review-pr` skills to match new script signatures

## [1.8.2] - 2026-03-04

### Fixed
- Script/schema paths in triage-findings, grumpy-review, and check-pr-comments skills now use `../../scripts/` and `../../schemas/` relative paths instead of bare `scripts/` (which resolved against agent cwd, not plugin root)
- Tightened `allowed-tools` globs to use exact command prefixes (e.g., `python3 ../../scripts/validate_report.py *`) instead of loose wildcards

## [1.8.1] - 2026-03-04

### Changed
- Rename `persistent-memory` skill references to `lessons-learned` across all workflow skills, agents, and docs

## [1.8.0] - 2026-03-04

### Added
- Lessons Learned phase to all workflow skills (feature, simplified, trivial) — reflects on task, saves insights via `memcan:lessons-learned` skill (if available), defaults to global memories, reports count of memories saved
- `lessons-learned` to claudius agent's Available Skills list
- `memcan` as optional plugin dependency in README (requires Docker Compose for Qdrant; install from `lklimek/agents` marketplace)

## [1.7.0] - 2026-03-04

### Changed
- Claudius agent is now a pure coordinator — selects skills/agents, plans, and delegates; never implements directly
- Merged `team-coordination` skill content into claudius agent definition (delegation style, spawning approaches, agent prompt requirements, worktree lifecycle, scaling, output conventions, anti-patterns)

### Removed
- `team-coordination` skill — consolidated into claudius agent

## [1.6.4] - 2026-03-04

### Changed
- Use `ghsudo` by default in all GitHub write-access scripts (`gh-post-review.sh`, `gh-request-reviewer.sh`, `gh-resolve-review-thread.sh`)
- Require plans to list skills, agents, and workflow skill in claudius agent

## [1.6.3] - 2026-03-04

### Changed
- Add severity re-evaluation step to grumpy-review dedup phase — agents must load the `severity` skill and strictly apply its criteria to combat over-inflation

## [1.6.2] - 2026-03-04

### Added
- Interactive filter/sort toolbar in standalone HTML report (`--format html`): severity filter, category filter, text search, sort by severity/ID/category with ascending/descending toggle
- Sort by severity regroups findings under severity headings (CRITICAL, HIGH, etc.) with color-coded borders
- Section hiding — entire finding sections collapse when all their findings are filtered out
- Visible count label ("Showing X of Y findings") updates dynamically
- Data attributes (`data-finding-id`, `data-severity`, `data-category`) on finding divs in base template, shared by both html and triage formats
- Sort order toggle button (▲/▼) for reversing sort direction

### Changed
- Refactored `render_triage()` to build on base template data attributes instead of re-patching them
- Toolbar hidden via `{% if not triage %}` guard — triage keeps its own richer toolbar
- Toolbar hidden in print via existing `.no-print` CSS rule

## [1.6.1] - 2026-03-04

### Added
- Test isolation rule in `coding-best-practices` — protect real user data by redirecting config/data/DB to temp paths

## [1.6.0] - 2026-03-04

### Changed
- Replace bundled `ghsu.py` script with [`ghsudo`](https://github.com/lklimek/ghsudo) pip package — install with `pip install ghsudo`
- Update all references in git-and-github skill, settings.example.json, and README to use `ghsudo` CLI command

### Removed
- `scripts/ghsu.py` — functionality now provided by the `ghsudo` package

## [1.5.1] - 2026-03-03

### Changed
- Add explicit "Skills" section with when-to-use descriptions to all agents that have skills: architect, developer-bilby, devops-engineer, project-reviewer, qa-engineer, security-engineer, ux-designer
- Replace generic "Tools Available" sections with focused skill listings
- developer-bilby now lists all language-specific skills (rust, python, go, frontend) alongside coding-best-practices and severity

## [1.5.0] - 2026-03-03

### Changed
- Rename `github` skill to `git-and-github` for clarity — updated all references in agents, skills, and README
- Update skill description to include access-denied issue handling

## [1.4.3] - 2026-03-03

### Changed
- Add explicit "Available Skills" reference list to claudius agent with names and usage triggers
- Trim claudius frontmatter `skills` to core three (github, severity, team-coordination); rest documented in body
- Reword all skill descriptions to start with "Use when/for" trigger pattern
- Simplify `allowed-tools` globs across skills (collapse verbose patterns into wildcards)

## [1.4.2] - 2026-03-03

### Changed
- Collapse all multi-line YAML frontmatter values to single-line strings across agents and skills
- Add frontmatter single-line convention to CLAUDE.md

## [1.4.1] - 2026-03-03

### Changed
- Condense claudius agent personality section — inline voice description, remove verbose bullet list
- Add explicit skill evaluation step in prompt processing instructions

## [1.4.0] - 2026-03-03

### Added
- `ghsu` (GitHub Sudo) — per-org encrypted token management for elevated GitHub access with cross-platform GUI approval dialogs (zenity/osascript/PowerShell), terminal fallback, and auto-detection of target org from command args or git remotes
- Elevated Permissions section in github skill with ghsu integration
- ghsu documentation in README

## [1.3.2] - 2026-03-03

### Changed
- Tighten comment brevity rule in `coding-best-practices`: 1 line great, 2 good, 3 mediocre
- Soften doc-comment rules across all language best-practices skills: one-line doc-comment always, expand only when non-obvious

## [1.3.1] - 2026-03-03

### Fixed
- Remove broken `UserPromptSubmit` prompt hook — LLM evaluator misinterpreted hook events; moved skills/agents reminder to agent instructions and CLAUDE.md instead

### Changed
- Add "Skills & Agents First" rule to claudius agent definition for reliable enforcement

## [1.3.0] - 2026-03-03

### Added
- `workflow-feature` skill — Feature development workflow (Requirements → Architecture → TDD → Implementation → QA)
- `workflow-simplified` skill — Simplified workflow for bug fixes and small changes
- `workflow-trivial` skill — Trivial workflow for typos and single-line fixes
- `team-coordination` skill — delegation, spawning, prompt requirements, worktree lifecycle, anti-patterns
- `python-best-practices` skill — Python standards, patterns, and review checklist
- `go-best-practices` skill — Go standards, concurrency, error handling, and review checklist
- `frontend-best-practices` skill — TypeScript/React/Vue/Svelte standards, accessibility, and review checklist
- `developer-bilby` agent — single polyglot developer (Bilby the Dev) replacing 4 language-specific agents
- `UserPromptSubmit` hook — reminds about available skills and agents before each response

### Changed
- Slim `claudius.md` from ~304 lines to ~83 lines by extracting workflows and team coordination into on-demand skills
- Workflow and delegation details now load fresh into context when invoked, reducing attention dilution in long conversations
- Condense all skill descriptions (~50% shorter) — focus on trigger conditions, not implementation details
- Condense all agent descriptions — focus on when to use, not capability lists
- Update claudius description to development lead role
- Expand `rust-best-practices` with technical standards, patterns, pitfalls, and review checklist from old agent

### Removed
- `rust-developer`, `python-developer`, `go-developer`, `frontend-developer` agents — replaced by `developer-bilby`
- `technical-researcher` agent — duties absorbed by `architect`

## [1.2.0] - 2026-03-03

### Added
- `coding-best-practices` skill — shared coding rules extracted from all developer agents (workflow discipline, code quality tool timing, review output format, security awareness, worktree discipline, cross-cutting rules)
- Meaningful-comments-only rule in `coding-best-practices` skill: don't comment self-explanatory code or simple one-liners

### Changed
- All developer agents now preload `coding-best-practices` skill instead of duplicating shared sections
- Removed ~1,300 tokens of duplicated boilerplate from developer agents
- Removed version pinning requirements from developer agents and devops-engineer — lock files handle reproducibility
- Added lock-file-aware dependency policy to project-reviewer and security-engineer: unpinned semver ranges are acceptable when ecosystem uses lock files (Cargo.lock, go.sum, package-lock.json)

## [1.1.0] - 2026-03-03

### Added
- Prior art check workflow step to all developer agents (rust, python, go, frontend) — forces searching package registries before implementing custom code
- M-PRIOR-ART checklist item to rust-best-practices skill
- Dependency justification checks to project-reviewer (custom implementations must be justified, new deps evaluated for health)
- Strengthened architect "prefer reuse" guidance with ecosystem-specific registry searches

## [1.0.1] - 2026-03-03

### Changed
- Remove "monkey" references from claudius agent personality
- Restructure README: promote grumpy-review section, simplify tables, add permissions note

## [1.0.0] - 2026-03-02

### Changed
- Graduate to stable release
- Update versioning guidelines to standard SemVer (major/minor/patch)

## [0.16.2] - 2026-03-02

### Added
- TDD Tests phase to all workflows
- UX-designer persona-first design and HTML wireframe delivery
- Decision explanation hints to triage UI
- User story section requirement for feature/enhancement issues
- Grumpy-review + triage-findings workflow documentation in README
- Substantive test assertion requirements in qa-engineer and project-reviewer
- Frontend-developer agent enhancements and plugin dependency documentation

### Fixed
- Harden permission rules to least-privilege

## [0.12.2] - 2026-02-27

### Added
- Unified report schema for check-pr-comments and triage-findings
- Severity inflation guard and code brevity directives
- Development in worktrees with wave-based cleanup
- Code deduplication directive
- Planning guidelines to claudius agent
- Workflow phase instructions pushed into specialist agents

### Changed
- Optimize github skill — remove well-known commands, tighten safety rules
- Slim claudius agent — remove redundant agents table

### Fixed
- Triage server startup, browser compatibility, and layout polish
- Make triage server multi-threaded with proper concurrency guards
- Port conflict error handling
- Remove packaging from workflow phases

## [0.11.3] - 2026-02-27

### Added
- JSON schema validation to grumpy-review and triage-findings
- Triage-to-review feedback loop with INTENTIONAL/TODO comments
- Agent contribution and dedup charts in report layout

### Fixed
- Triage server deadlock, sticky notification banner, fetch timeouts

## [0.10.0] - 2026-02-27

### Added
- Unified review report pipeline with interactive triage
- JSON finding format for review agents
- Documentation conventions to claudius agent
- QA phase to trivial workflow and QA gate rule
- Trivial workflow for minimal changes

### Changed
- Rename review-all to grumpy-review

## [0.8.2] - 2026-02-27

### Added
- Full workflow to claudius agent
- Workflow documentation: iteration policy, severity levels, trivial workflow

## [0.7.0] - 2026-02-26

### Added
- Merge-base skill
- Stuck agent recovery guideline with opus retry
- Structured header with branch/commit to review reports
- Notify-agentes workflow

### Changed
- Rename code-reviewer to project-reviewer
- Rename review skill to review-all
- Merge personality skill into claudius agent

### Fixed
- Exclude non-actionable findings from PR inline comments

## [0.5.7] - 2026-02-24

### Added
- Claudius attribution footer
- Expanded settings.example.json with git, gh CLI, and deny rules

### Changed
- Condense qa-engineer agent and add manual test scenarios
- Restructure code-reviewer into project consistency specialist
- Create PRs as draft by default

### Fixed
- Enforce full file paths in review findings and stricter git safety rules
- Developer agents only run linting/tests before commits
- Use mktemp session dirs instead of hardcoded /tmp paths
- Enforce wrapper scripts over raw gh api in github skill

## [0.4.0] - 2026-02-23

### Added
- Review skill and expanded team coordination
- Severity classification skill
- OWASP cheat sheets and ASVS as local references
- Rust-analyzer LSP awareness in rust-best-practices skill
- Condensed reference index in security-best-practices skill

### Fixed
- Code review findings addressed

## [0.3.0] - 2026-02-22

### Added
- Semantic versioning
- Agent tools, skills, and required permissions documentation
- PR review comment operations consolidated into github skill

### Changed
- Claudius personality configuration

## [0.1.0] - 2026-02-20

### Added
- Initial plugin scaffold with agents and skills
- Security-best-practices skill with eval results
- Rust-best-practices skill with eval results
- Claude marketplace configuration
- 13 specialist agents: architect, business-domain-analyst, devops-engineer, frontend-developer, go-developer, project-reviewer, python-developer, qa-engineer, rust-developer, security-engineer, technical-researcher, technical-writer, ux-designer
- Claudius coordinator agent

[4.0.0]: https://github.com/lklimek/claudius/compare/v3.14.5...v4.0.0
[3.14.5]: https://github.com/lklimek/claudius/compare/v3.14.4...v3.14.5
[3.14.4]: https://github.com/lklimek/claudius/compare/v3.14.3...v3.14.4
[3.14.3]: https://github.com/lklimek/claudius/compare/v3.14.2...v3.14.3
[3.14.2]: https://github.com/lklimek/claudius/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/lklimek/claudius/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/lklimek/claudius/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/lklimek/claudius/compare/v3.12.0...v3.13.0
[2.2.0]: https://github.com/lklimek/claudius/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/lklimek/claudius/compare/v2.0.0...v2.1.0
[1.8.0]: https://github.com/lklimek/claudius/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/lklimek/claudius/compare/v1.6.4...v1.7.0
[1.6.4]: https://github.com/lklimek/claudius/compare/v1.6.3...v1.6.4
[1.6.3]: https://github.com/lklimek/claudius/compare/v1.6.2...v1.6.3
[1.6.1]: https://github.com/lklimek/claudius/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/lklimek/claudius/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/lklimek/claudius/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/lklimek/claudius/compare/v1.4.3...v1.5.0
[1.4.3]: https://github.com/lklimek/claudius/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/lklimek/claudius/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/lklimek/claudius/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/lklimek/claudius/compare/v1.3.2...v1.4.0
[1.3.0]: https://github.com/lklimek/claudius/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/lklimek/claudius/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/lklimek/claudius/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/lklimek/claudius/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/lklimek/claudius/compare/v0.16.2...v1.0.0
[0.16.2]: https://github.com/lklimek/claudius/compare/v0.12.2...v0.16.2
[0.12.2]: https://github.com/lklimek/claudius/compare/v0.11.3...v0.12.2
[0.11.3]: https://github.com/lklimek/claudius/compare/v0.10.0...v0.11.3
[0.10.0]: https://github.com/lklimek/claudius/compare/v0.8.2...v0.10.0
[0.8.2]: https://github.com/lklimek/claudius/compare/v0.7.0...v0.8.2
[0.7.0]: https://github.com/lklimek/claudius/compare/v0.5.7...v0.7.0
[0.5.7]: https://github.com/lklimek/claudius/compare/v0.4.0...v0.5.7
[0.4.0]: https://github.com/lklimek/claudius/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lklimek/claudius/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/lklimek/claudius/releases/tag/v0.1.0
