# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project uses [Semantic Versioning](https://semver.org/).

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
