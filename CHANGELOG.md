# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project uses [Semantic Versioning](https://semver.org/).

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
