# CLAUDE.md

Guidance for Claude Code working in this repository.

## Project Overview

**Claudius** — a Claude Code plugin at [github.com/lklimek/claudius](https://github.com/lklimek/claudius). Reusable agents and skills for development workflows. GPL-3.0.

## Repository Structure

```
.claude-plugin/
  plugin.json       # Plugin manifest (only `name` required; agents/ and skills/ auto-discovered)
agents/             # Agent definitions (.md files with YAML frontmatter)
skills/             # Skill definitions (directories with SKILL.md + optional resources)
scripts/            # Helper scripts used by skills (Python + shell)
schemas/            # JSON Schema definitions for shared data formats
```

## Agents

Single `.md` file with YAML frontmatter. Body is the agent's system prompt.

```yaml
---
name: agent-name
description: "When to use this agent."
tools: Read, Grep, Glob, Bash   # omit Edit/Write for read-only agents
model: inherit                   # inherit | sonnet | opus | haiku
---
```

Other fields: `disallowedTools`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory` (user|project|local), `background`, `isolation` (worktree).

## Skills

Directory with `SKILL.md` (YAML frontmatter + instructions) and optional subdirs (`references/`, `scripts/`).

```yaml
---
name: skill-name
description: When and how this skill should be invoked.
---
```

Other fields: `argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `context` (fork), `agent`, `hooks`.

Substitutions: `$ARGUMENTS`, `$0`/`$1`/etc., `${CLAUDE_SESSION_ID}`, `` !`command` ``.

### Bundled File References

Skills support `${CLAUDE_SKILL_DIR}` substitution — resolves to the skill's directory at load time.

- **Instructions**: `${CLAUDE_SKILL_DIR}/../../scripts/foo.py` for plugin-root scripts. Relative paths (`scripts/helper.py`, `[ref](references/ref.md)`) for skill-local files.
- **`allowed-tools`**: path-agnostic globs (e.g., `Bash(*my-script.py *)`) — variable substitution in frontmatter is unreliable.
- **`${CLAUDE_PLUGIN_ROOT}`**: only for hooks and MCP JSON configs, NOT for skill/command markdown.

## Conventions

- Names: lowercase kebab-case (`security-engineer.md`, `my-skill/`)
- Self-contained: each agent/skill works independently
- Frontmatter `description`: state **when** to use, not just what it does
- Prefer minimal tool sets; read-only agents omit Edit/Write
- `allowed-tools` Bash globs must be as specific as possible — match exact script names (e.g., `Bash(*gh-resolve-review-threads.sh *)`) not generic patterns (e.g., `Bash(*gh-*.sh *)`)
- Concise by default — every change (code, docs, descriptions, instructions, commit/PR/changelog text): same value, fewer tokens.
- Frontmatter values: single-line strings, no YAML folded/literal scalars (`>`, `|`). Use long lines instead of wrapping.
- **No redundant content**: never duplicate information that lives in another skill, referenced doc, or well-known spec. If a skill loads `git-and-github`, don't repeat git commands. If it references [Keep a Changelog](https://keepachangelog.com/), don't reproduce the format. Delegate to the source — don't inline it.
- **Self-review before finishing**: scan all modified agents/skills for content that restates what a loaded skill or referenced doc already provides. Remove it.

## Development

```bash
claude --plugin-dir /home/ubuntu/git/claudius   # local testing
claude plugin validate .                         # validate manifest
```

## Versioning

**Every PR that changes plugin content MUST bump `plugin.json`'s version — exactly once per PR, before it merges** to a base branch (main/master/vX.Y-dev). Do it once you know the PR is ready, not on the first commit and not again on every follow-up commit: follow-up commits on a still-open, unmerged PR revise the same unreleased change, so re-bump only if the change's nature grows (e.g. patch → minor) — never skip the bump entirely just because it's "only one commit so far" or "not merged yet." Follow [SemVer 2](https://semver.org/).

- **Major** (x.0.0): breaking changes to agent/skill interfaces, removed components, incompatible frontmatter changes
- **Minor** (0.x.0): new agents/skills, new frontmatter fields, significant behavior changes
- **Patch** (0.0.x): bug fixes, doc corrections, minor wording changes

Update `CHANGELOG.md` with every version bump. Follow [Keep a Changelog](https://keepachangelog.com/) format.

**Backward compatibility applies only to what's already merged to a base branch.** Code in an unmerged PR (yours or another still-open one) isn't released — freely reshape it, including its own prior commits, without preserving compatibility with itself. Compatibility constraints (and the Major/Minor bump distinctions above) only bind once a version has actually merged.

## Required Skills (plugin-dev)

Before modifying plugin components, load the matching `plugin-dev` skill from [claude-plugins-official](https://github.com/anthropics/claude-plugins-official):

- Before modifying an **agent** → load `plugin-dev:agent-development`
- Before modifying a **skill** → load `plugin-dev:skill-development`
- Before modifying **hooks** → load `plugin-dev:hook-development`
- Before modifying **plugin structure or plugin.json** → load `plugin-dev:plugin-structure`
- After creating/modifying an agent → run `plugin-dev:agent-creator` or `plugin-dev:skill-reviewer` to validate
- After modifying plugin components → ALWAYS run `plugin-dev:plugin-validator` to check structure before finishing

## Safety: Destructive Data Operations

**NEVER** delete databases, wipe Docker volumes, drop tables, or perform any irreversible data loss without explicit user confirmation — even in dev environments. When a data-related error occurs (migration checksum mismatch, schema conflict, corrupt state):

1. **Present the problem** — explain what happened and why
2. **Offer options** — reset DB, revert migration, manual fix, or other recovery paths
3. **Wait for explicit user choice** — never auto-select the destructive option

This applies to all agents. Automated crash-loop recovery must never silently destroy data.

## Temporary Files

Use `tmp/` (gitignored) for eval workspaces and transient artifacts.
