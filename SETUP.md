# Claudius Setup Guide

The detailed manual for [Claudius the Magnificent](README.md). Everything you need to configure, customize, and get the most out of the plugin. I trust you can follow instructions -- let's find out.

## Prerequisites

### GH_TOKEN -- GitHub Personal Access Token

All agents connect to the [GitHub MCP server](https://github.com/github/github-mcp-server) for direct GitHub API access (issues, PRs, code search, actions, etc.). This requires a GitHub Personal Access Token set as `GH_TOKEN`.

**Step 1 -- Create a fine-grained PAT:**

[-> Create a new fine-grained PAT with pre-selected permissions](https://github.com/settings/personal-access-tokens/new?name=Claudius+GitHub+MCP&actions=write&contents=write&discussions=read&issues=write&metadata=read&pull_requests=write)

The link above pre-fills these **repository permissions**:

| Permission | Access | Used for |
|---|---|---|
| **Actions** | Read and write | View workflow runs and logs, trigger workflows |
| **Contents** | Read and write | Read code, push to branches |
| **Discussions** | Read-only | Read repository discussions |
| **Issues** | Read and write | Create issues, add comments |
| **Metadata** | Read-only | Basic repository metadata (always required) |
| **Pull requests** | Read and write | Create PRs, review, comment, resolve threads |

Set the token expiration and repository access scope as needed, then create the token.

> **Tip:** The GitHub MCP server auto-detects your token's permissions and hides tools you don't have access to. Start with the permissions above and add more if needed.

**Step 2 -- Configure the token:**

Add `GH_TOKEN` to your Claude Code settings:

```json
// ~/.claude/settings.json
{
  "env": {
    "GH_TOKEN": "github_pat_..."
  }
}
```

Or export it in your shell profile (`~/.bashrc`, `~/.zshrc`):

```bash
export GH_TOKEN="github_pat_..."
```

**Step 3 -- Verify:**

Restart Claude Code and run `/mcp` -- the `github` server should appear as connected.

### Docker Compose for memcan

The `memcan` plugin requires Docker Compose for Qdrant (vector DB) and optionally Neo4j. See the [memcan README](https://github.com/lklimek/memcan) for setup instructions. Install from the `lklimek/agents` marketplace:

```
/plugin marketplace add lklimek/agents
/plugin install memcan@lklimek
```

## Agents

| Agent | Description |
|-------|-------------|
| `claudius` | Team coordinator. Magnificently arrogant, always right. |
| `architect-nagatha` | System architecture, module boundaries, API design, dependency review |
| `project-reviewer-adams` | Project consistency, cross-artifact validation, convention adherence, structural/idiom code-quality review (readability, naming, DRY, cross-file consistency) |
| `developer-bilby` | Code changes in any language |
| `qa-engineer-marvin` | Test plans, automated tests, edge case identification, coverage analysis, adversarial execution-focused code-quality review (running tests/linters, edge cases, error handling, races) |
| `security-engineer-smythe` | OWASP Top 10, dependency scanning, secret detection, secure coding review |
| `technical-writer-trillian` | README, API docs, tutorials, guides, changelogs, runbooks |
| `ux-designer-diziet` | Requirements, domain analysis, UI flows, interaction patterns, accessibility |

### Optional Plugin Dependencies

Some agents delegate to skills from external plugins for specialized capabilities. These plugins are **not required** -- agents work without them -- but installing them unlocks additional quality.

| Agent | External Skill | Plugin | Benefit |
|-------|---------------|--------|---------|
| `developer-bilby` | `frontend-design` | [`claude-plugins-official`](https://github.com/anthropics/claude-plugins-official) | Design quality guidance for high-fidelity UI work |
| `developer-bilby` | `rust-analyzer-lsp` | [`claude-plugins-official`](https://github.com/anthropics/claude-plugins-official) | LSP diagnostics, go-to-definition, type inference for `.rs` files |
| `claudius` (all workflows) | `lessons-learned` | [`memcan`](https://github.com/lklimek/memcan) | Persistent lessons-learned memory across sessions |

> **Note:** `plugin.json` does not yet support a `dependencies` field. Until then, install optional dependencies manually.

## GitHub MCP Server

All agents connect to the [GitHub MCP server](https://github.com/github/github-mcp-server) for direct GitHub API access (issues, PRs, code search, actions, etc.). This requires a GitHub Personal Access Token -- see [Prerequisites](#gh_token----github-personal-access-token) above.

## ghsudo -- Elevated GitHub Access (Optional)

**What this does:** ghsudo adds a **two-token model** for GitHub access: your default `gh` token is read-only, and write operations require explicit human approval via a GUI dialog. This is **optional** -- by default, Claudius uses your `gh` token directly for all operations, and the GitHub MCP server uses `GH_TOKEN`. Install ghsudo only if you want an extra approval gate on write operations.

**How it works:**

1. Claude operates day-to-day with a **read-only** GitHub token (clone, fetch, view PRs, read issues).
2. When a command needs write access (push, merge, create PR), GitHub returns 403 Forbidden.
3. Claude re-runs the failed command through `ghsudo <command>`.
4. ghsudo detects the target org, shows a GUI dialog (or terminal prompt) with the exact command, and waits for human approval.
5. If approved, ghsudo decrypts that org's **read-write** token and re-executes with `GH_TOKEN` set. The write token exists in memory only for the duration of that single command.

Supports **per-organization tokens** -- each GitHub org/owner gets its own encrypted read-write token. The target org is auto-detected from `-R owner/repo` flags or git remotes.

**Prerequisites:**

- `pip install ghsudo`
- `gh auth setup-git` -- configures git's credential helper so HTTPS remotes work with `gh`
- Git remotes must use HTTPS (`https://github.com/...`), not SSH -- update with:
  `git remote set-url origin https://github.com/OWNER/REPO.git`

**Step 1 -- Log in to `gh` with a read-only token:**

```bash
gh auth login
```

When prompted, select **GitHub.com -> HTTPS -> Paste an authentication token**. Use a [fine-grained PAT](https://github.com/settings/personal-access-tokens/new) with **read-only** repository permissions (Contents: Read, Metadata: Read). This becomes Claude's default token -- it can browse code and PRs but cannot modify anything.

Then configure git to use this token for HTTPS operations:

```bash
gh auth setup-git
```

**Step 2 -- Generate a read-write token and store it with ghsudo:**

Create a second [fine-grained PAT](https://github.com/settings/personal-access-tokens/new) scoped to the target organization with **read-write** permissions:

- **Contents:** Read and write (push, create branches)
- **Pull requests:** Read and write (create, merge, comment)
- **Issues:** Read and write (create, comment, label)
- **Workflows:** Read and write (if CI is needed)
- Add other permissions as needed for your workflow.

Then store it with ghsudo (per org, per machine):

```bash
ghsudo --setup dashpay    # store write token for dashpay org
ghsudo --setup lklimek    # store write token for lklimek org
ghsudo --list             # see stored orgs
```

| Option | Description |
|--------|-------------|
| `<command...>` | Default: show approval dialog -> decrypt -> execute with elevated token |
| `--org ORG` | Specify target org (auto-detected from `-R` flag or git remote if omitted) |
| `--no-gui` | Skip GUI dialog, use terminal prompt only |
| `--setup <org>` | Prompt for PAT, validate, encrypt, store for org |
| `--verify [org]` | Verify specific org's token, or all if omitted |
| `--revoke [org]` | Revoke specific org's token, or all if omitted |
| `--list` | List orgs with stored tokens |

See [ghsudo on GitHub](https://github.com/lklimek/ghsudo) for full documentation and security details.

## Recommended Permissions

The autonomous skills (`ci-dance`, `review-dependency`, `review-pr`, `check-pr-comments`, `grumpy-review`) issue git and GitHub CLI commands. Without pre-approved permissions, Claude Code will prompt you to confirm each command interactively -- which defeats the purpose of autonomous operation.

Copy [`settings.example.json`](settings.example.json) into your project's `.claude/settings.json` to auto-approve the commands these skills need. The example includes a deny list that blocks destructive operations (force push, hard reset, branch force-delete) regardless of what is allowed.

> **Note:** The maintainer typically runs Claude Code with `--dangerously-skip-permissions` in an isolated environment, so the permission list in `settings.example.json` may be incomplete or outdated. PRs improving it are welcome.

## Skill Catalog

| Name | Description |
|------|-------------|
| `check-pr-comments` | Verify that PR review comments have been addressed |
| `ci-dance` | End-to-end PR pipeline -- push, CI monitoring, parallel reviews, fix, repeat until green |
| `coding-best-practices` | Universal rules for TDD, self-review, quality timing, review format, security |
| `dependabot-merge` | Bulk-process dependabot PRs -- audit, comment, merge safe ones, rebase failures |
| `frontend-best-practices` | Frontend best practices -- TypeScript, React/Vue/Svelte, CSS, accessibility, testing |
| `git-and-github` | All git/gh commands, GitHub interactions, and access-denied issues |
| `go-best-practices` | Go best practices -- idioms, error handling, concurrency, testing patterns |
| `grumpy-review` | Multi-agent code review with consolidated severity-ranked report |
| `lessons-learned` | Extract and save reusable learnings from the session |
| `merge-base` | Careful merge of remote base branch into current feature branch |
| `push` | Commit, push, and create/update PR -- auto-creates feature branch if on base |
| `python-best-practices` | Python best practices -- PEP 8, type hints, testing, error handling |
| `release` | Bump version (SemVer), update changelog, commit, push, and create GitHub release |
| `report-format` | Unified review report format for all finding-producing agents |
| `review-dependency` | Security-focused dependency update review |
| `review-pr` | Audit and review pull requests |
| `rust-best-practices` | Rust programming checklists (Microsoft Pragmatic + Rust API Guidelines) |
| `security-best-practices` | OWASP-based secure programming checklists |
| `severity` | Consistent severity classification (CRITICAL-INFO) for review findings |
| `triage-findings` | Interactive finding triage -- classify in browser, decisions feed back to Claude |
| `workflow-feature` | Full workflow for new features or major refactoring |
| `workflow-simplified` | Lighter workflow for bug fixes or small changes |

## Evaluated Skills

### Skill: `security-best-practices`

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
- **Lower debatable rate**: With the skill, 11-18% of findings are debatable vs. 21-24% without, indicating more precisely targeted recommendations.

### Skill: `rust-best-practices`

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
- **Lower debatable rate**: With the skill, 15-25% of findings are debatable vs. 23-31% without, and no false positives vs. 1 without.

## Sources

| Skill | Source |
|-------|--------|
| `security-best-practices` | [OWASP Cheat Sheet Series](https://github.com/OWASP/CheatSheetSeries) |
| `rust-best-practices` | [Microsoft Rust Guidelines](https://microsoft.github.io/rust-guidelines/) ([checklist](https://microsoft.github.io/rust-guidelines/guidelines/checklist/index.html)), [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) ([checklist](https://rust-lang.github.io/api-guidelines/checklist.html)) |

## License

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.en.html).
