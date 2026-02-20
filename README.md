# Claudius

A [Claude Code](https://claude.ai/code) plugin that provides a collection of reusable agents and skills for software development workflows. Agents cover the full development lifecycle -- from requirements gathering and architecture design through implementation, testing, security audit, and documentation. Skills add task-specific capabilities such as CI monitoring, dependency review, and pull request workflows.

## Installation

Install from the plugin marketplace:

```
/plugin marketplace add lklimek/claudius
```

Alternatively, clone the repository and point Claude Code at it directly:

```bash
git clone https://github.com/lklimek/claudius.git
claude --plugin-dir /path/to/claudius
```

## Agents

| Name | Description |
|------|-------------|
| `architect` | System architecture design, module boundaries, API design, dependency review |
| `business-domain-analyst` | Business requirements, stakeholder analysis, user stories, acceptance criteria |
| `code-reviewer` | Code quality, duplication detection, standards enforcement, documentation verification |
| `devops-engineer` | Docker, CI/CD pipelines, GitHub Actions, infrastructure configuration |
| `frontend-developer` | TypeScript/JavaScript, React/Vue/Svelte, CSS/styling, frontend tooling |
| `go-developer` | Go implementation, idiomatic patterns, table-driven tests |
| `python-developer` | Python implementation, PEP 8, pytest |
| `qa-engineer` | Test plans, automated tests, edge case identification, coverage analysis |
| `rust-developer` | Rust implementation, ownership patterns, Cargo |
| `security-engineer` | OWASP Top 10, dependency scanning, secret detection, secure coding review |
| `technical-researcher` | Technology evaluation, feasibility studies, library/framework comparison |
| `technical-writer` | README, API docs, tutorials, guides, changelogs, runbooks |
| `ux-designer` | User flows, wireframes, interaction patterns, accessibility audit |

## Skills

| Name | Description |
|------|-------------|
| `check-pr-comments` | Verify that PR review comments have been addressed |
| `ci-loop` | Autonomous CI monitoring and fix loop |
| `github` | GitHub workflow guidelines covering git and gh usage |
| `review-dependency` | Security-focused dependency update review |
| `review-loop` | Autonomous peer review feedback loop |
| `review-pr` | Audit and review pull requests |
| `rust-best-practices` | Rust programming checklists and reference material |

## License

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.en.html).
