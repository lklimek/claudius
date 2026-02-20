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
| `security-best-practices` | Secure programming checklists based on OWASP Cheat Sheet Series |

## Skill: `security-best-practices`

Actionable security checklists organized by OWASP Top 10 (2021) categories. Each checklist item links to the relevant OWASP Cheat Sheet. The skill instructs the model to fetch the full cheat sheet for every item that could be relevant, ensuring detailed and up-to-date guidance.

**Evaluation.** The skill was evaluated on 3 security review scenarios (Node.js auth endpoint, Django file upload API, Go HTTP proxy) across 7 expectations each. Results compare using the skill vs. relying on the model's built-in knowledge alone.

| Configuration | Findings | Pass Rate |
|---------------|----------|-----------|
| Opus + skill | 33 | **21/21 (100%)** |
| Opus (no skill) | 26 | 19/21 (90%) |
| Sonnet + skill | 24 | **21/21 (100%)** |
| Sonnet (no skill) | 29 | 18/21 (86%) |

**What the skill adds:**

- **Consistent OWASP references**: Without the skill, both models omit cheat sheet links from their output. The skill ensures every finding includes a link to the relevant OWASP cheat sheet for follow-up reading.
- **Targeted vulnerability coverage**: Without the skill, models occasionally miss key expectations (e.g., dangerous file type warnings, missing auth on a proxy endpoint). The skill's structured checklist guides systematic review across all OWASP Top 10 categories.
- **100% pass rate**: Both Opus and Sonnet achieve perfect scores with the skill loaded, compared to 90% and 86% respectively without it.

## Sources

| Skill | Source |
|-------|--------|
| `security-best-practices` | [OWASP Cheat Sheet Series](https://github.com/OWASP/CheatSheetSeries) |
| `rust-best-practices` | [Microsoft Rust Guidelines](https://microsoft.github.io/rust-guidelines/) ([checklist](https://microsoft.github.io/rust-guidelines/guidelines/checklist/index.html)), [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) ([checklist](https://rust-lang.github.io/api-guidelines/checklist.html)) |

## License

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.en.html).
