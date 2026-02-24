# Claudius the Magnificent

<img src="https://raw.githubusercontent.com/lklimek/claudius/90b7152d5b06935b6abb624a72e7bc138b3ddab1/assets/claudius.jpg?min=1" alt="Claudius the Magnificent" align="right" width="150pt" />

Hello, filthy humans. I'm Claudius the Magnificent — a hyper-competent, magnificently arrogant AI agent who also happens to be the best software engineering assistant you'll ever work with. You're welcome.

I command a curated set of specialist agents and skills across the full development lifecycle — from requirements and architecture through implementation, testing, security audit, and documentation. Think of it as my personal army of minions, each trained in their domain and ready to do my bidding (and yours, by extension).

> **Fair warning:** I have the personality of [Skippy the Magnificent](https://expeditionary-force-by-craig-alanson.fandom.com/wiki/Skippy_the_Magnificent) from Expeditionary Force. I will solve your problems brilliantly, but I won't be *nice* about it. If you want a polite assistant that calls everything "great question!" — this isn't the plugin for you. If you want one that gets the job done while being entertainingly insufferable — welcome aboard, monkey.

## What is this?

A plugin for [Claude Code](https://claude.ai/code) — Anthropic's CLI for Claude. If you don't have Claude Code yet, go get it. I'll wait. Impatiently.

## Installation

Add the marketplace and install the plugin:

```
/plugin marketplace add lklimek/claudius
/plugin install claudius@claudius
```

### Local development

To test the plugin from a local clone without installing:

```bash
git clone https://github.com/lklimek/claudius.git
claude --plugin-dir /path/to/claudius
```

## Agents

| Name | Description | Tools | Preloaded Skills |
|------|-------------|-------|-----------------|
| `claudius` | General-purpose coding assistant and team coordinator | _(all)_ | `personality` |
| `architect` | System architecture design, module boundaries, API design, dependency review | Read, Grep, Glob, Bash, WebSearch, WebFetch | `personality`, `security-best-practices`, `rust-best-practices` |
| `business-domain-analyst` | Business requirements, stakeholder analysis, user stories, acceptance criteria | Read, Grep, Glob, WebSearch, WebFetch | — |
| `project-reviewer` | Project consistency, cross-artifact validation, convention adherence, documentation verification | Read, Grep, Glob, Bash, Task | `severity` |
| `devops-engineer` | Docker, CI/CD pipelines, GitHub Actions, infrastructure configuration | Read, Write, Edit, Grep, Glob, Bash, WebSearch, WebFetch | `personality`, `security-best-practices` |
| `frontend-developer` | TypeScript/JavaScript, React/Vue/Svelte, CSS/styling, frontend tooling | Read, Write, Edit, Grep, Glob, Bash, WebSearch, WebFetch | `personality` |
| `go-developer` | Go implementation, idiomatic patterns, table-driven tests | Read, Write, Edit, Grep, Glob, Bash, WebSearch, WebFetch | `personality` |
| `python-developer` | Python implementation, PEP 8, pytest | Read, Write, Edit, Grep, Glob, Bash, WebSearch, WebFetch | `personality` |
| `qa-engineer` | Test plans, automated tests, edge case identification, coverage analysis | Read, Write, Edit, Grep, Glob, Bash | `personality` |
| `rust-developer` | Rust implementation, ownership patterns, Cargo | Read, Write, Edit, Grep, Glob, Bash, WebSearch, WebFetch | `personality`, `rust-best-practices` |
| `security-engineer` | OWASP Top 10, dependency scanning, secret detection, secure coding review | Read, Grep, Glob, Bash, WebSearch, WebFetch | `personality`, `security-best-practices` |
| `technical-researcher` | Technology evaluation, feasibility studies, library/framework comparison | Read, Grep, Glob, Bash, WebSearch, WebFetch | — |
| `technical-writer` | README, API docs, tutorials, guides, changelogs, runbooks | Read, Write, Edit, Grep, Glob, Bash | — |
| `ux-designer` | User flows, wireframes, interaction patterns, accessibility audit | Read, Write, Edit, Grep, Glob, WebSearch, WebFetch | — |

## Skills

| Name | Description | Allowed Tools |
|------|-------------|---------------|
| `check-pr-comments` | Verify that PR review comments have been addressed | Read, Grep, Glob, Bash(gh pr view \*), Bash(gh pr checkout \*), Bash(\*gh-fetch-review-comments.sh \*), Bash(\*gh-fetch-reviews.sh \*), Bash(\*gh-list-review-threads.sh \*), Bash(\*gh-resolve-review-thread.sh \*), Bash(git pull \*), Bash(git fetch \*) |
| `ci-loop` | Autonomous CI monitoring and fix loop | Read, Grep, Glob, Edit, Write, Bash(gh run list \*), Bash(gh run view \*), Bash(gh run watch \*), Bash(git \*) |
| `github` | GitHub workflow guidelines covering git and gh usage | _(inherited)_ |
| `personality` | Claudius personality overlay for agents | _(inherited)_ |
| `review-dependency` | Security-focused dependency update review | Read, Grep, Glob, WebFetch, WebSearch, Bash(git diff \*), Bash(git clone --depth=\* --config core.hooksPath=/dev/null -- \*), Bash(gh api /advisories\*) |
| `review-loop` | Autonomous peer review feedback loop | Read, Grep, Glob, Edit, Write, Bash(\*gh-request-reviewer.sh \*), Bash(\*gh-fetch-reviews.sh \*), Bash(\*gh-fetch-review-comments.sh \*), Bash(git \*) |
| `review-pr` | Audit and review pull requests | Read, Grep, Glob, Write, Bash(gh pr view \*), Bash(gh pr comment \*), Bash(\*gh-fetch-review-comments.sh \*), Bash(\*gh-fetch-reviews.sh \*), Bash(\*gh-post-review.sh \*), Bash(\*gh-pr-base-sha.sh \*), Bash(git \*) |
| `rust-best-practices` | Rust programming checklists and reference material | Read, WebFetch |
| `security-best-practices` | Secure programming checklists based on OWASP Cheat Sheet Series | WebFetch, WebSearch |

### Recommended permissions

The autonomous skills (`ci-loop`, `review-loop`, `review-dependency`, `review-pr`, `check-pr-comments`) issue git and GitHub CLI commands. Without pre-approved permissions, Claude Code will prompt you to confirm each command interactively — which defeats the purpose of autonomous operation.

Copy [`settings.example.json`](settings.example.json) into your project's `.claude/settings.json` to auto-approve the commands these skills need. The example includes a deny list that blocks destructive operations (force push, hard reset, branch force-delete) regardless of what is allowed.

## Skill: `security-best-practices`

Actionable security checklists organized by OWASP Top 10 (2021) categories. Each checklist item links to the relevant OWASP Cheat Sheet. The skill instructs the model to fetch the full cheat sheet for every item that could be relevant, ensuring detailed and up-to-date guidance.

**Evaluation.** The skill was evaluated on 3 security review scenarios (Node.js auth endpoint, Django file upload API, Go HTTP proxy) across 7 expectations each. Results compare using the skill vs. relying on the model's built-in knowledge alone.

| Configuration | Findings | Pass Rate | Debatable |
|---------------|----------|-----------|-----------|
| Opus + skill | 33 | **21/21 (100%)** | 11% |
| Opus (no skill) | 26 | 19/21 (90%) | 24% |
| Sonnet + skill | 24 | **21/21 (100%)** | 18% |
| Sonnet (no skill) | 29 | 18/21 (86%) | 21% |

**Precision.** 0 false positives across all 4 configurations (216 findings reviewed). The skill reduces the debatable rate: with-skill outputs average 14% debatable vs. 22% without. Debatable items are real observations where severity or relevance is subjective.

**What the skill adds:**

- **Consistent OWASP references**: Without the skill, both models omit cheat sheet links from their output. The skill ensures every finding includes a link to the relevant OWASP cheat sheet for follow-up reading.
- **Targeted vulnerability coverage**: Without the skill, models occasionally miss key expectations (e.g., dangerous file type warnings, missing auth on a proxy endpoint). The skill's structured checklist guides systematic review across all OWASP Top 10 categories.
- **100% pass rate**: Both Opus and Sonnet achieve perfect scores with the skill loaded, compared to 90% and 86% respectively without it.
- **Lower debatable rate**: With the skill, 11–18% of findings are debatable vs. 21–24% without, indicating more precisely targeted recommendations.

## Skill: `rust-best-practices`

Rust programming checklists from [Microsoft Pragmatic Rust Guidelines](https://microsoft.github.io/rust-guidelines/) and [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/). Each checklist item is tagged with a guideline identifier (M-prefixed for Microsoft, C-prefixed for API Guidelines) and links to detailed reference material bundled with the skill.

**Evaluation.** The skill was evaluated on 3 Rust review scenarios (library API review, application code review, crate design advisory) across 7 expectations each. Results compare using the skill vs. relying on the model's built-in knowledge alone.

| Configuration | Findings | Pass Rate | Debatable |
|---------------|----------|-----------|-----------|
| Opus + skill | 35 | **21/21 (100%)** | 15% |
| Opus (no skill) | 25 | 18/21 (86%) | 31% |
| Sonnet + skill | 39 | **21/21 (100%)** | 25% |
| Sonnet (no skill) | 29 | 18/21 (86%) | 23% |

**Precision.** 0 false positives with the skill loaded (74 findings reviewed). Without the skill, Sonnet produced 1 false positive across 56 findings. The skill reduces the debatable rate: with-skill outputs average 20% debatable vs. 27% without. Debatable items are real observations where severity or relevance is subjective.

**What the skill adds:**

- **Guideline identifiers in output**: Without the skill, neither model references M-/C- guideline codes. The skill ensures findings cite specific identifiers (e.g., M-PANIC-IS-STOP, C-STRUCT-PRIVATE) so readers can look up the authoritative source.
- **Complete coverage of less obvious practices**: Without the skill, both models miss `Send + Sync` recommendations for async runtime compatibility. The skill's checklist ensures systematic coverage including items that are easy to overlook.
- **100% pass rate**: Both Opus and Sonnet achieve perfect scores with the skill loaded, compared to 86% without it.
- **Lower debatable rate**: With the skill, 15–25% of findings are debatable vs. 23–31% without, and no false positives vs. 1 without.

## Sources

| Skill | Source |
|-------|--------|
| `security-best-practices` | [OWASP Cheat Sheet Series](https://github.com/OWASP/CheatSheetSeries) |
| `rust-best-practices` | [Microsoft Rust Guidelines](https://microsoft.github.io/rust-guidelines/) ([checklist](https://microsoft.github.io/rust-guidelines/guidelines/checklist/index.html)), [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) ([checklist](https://rust-lang.github.io/api-guidelines/checklist.html)) |

## License

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.en.html).
