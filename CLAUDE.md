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

Skills resolve relative paths from their base directory at invocation time.

- **Instructions**: relative paths (e.g., `scripts/my-script.py arg1`)
- **`allowed-tools`**: path-agnostic globs (e.g., `Bash(*my-script.py *)`) — install path is unknown at authoring time
- **Reference docs**: relative markdown links (e.g., `[ref](references/ref.md)`)
- No `$SKILL_DIR` variable exists in SKILL.md. `${CLAUDE_PLUGIN_ROOT}` is only for hooks/MCP configs.

## Conventions

- Names: lowercase kebab-case (`security-engineer.md`, `my-skill/`)
- Self-contained: each agent/skill works independently
- Frontmatter `description`: state **when** to use, not just what it does
- Prefer minimal tool sets; read-only agents omit Edit/Write
- Keep all descriptions and instructions concise — fewer tokens, same signal

## Development

```bash
claude --plugin-dir /home/ubuntu/git/claudius   # local testing
claude plugin validate .                         # validate manifest
```

## Versioning

Bump version in `plugin.json` before each commit. Follow [SemVer 2](https://semver.org/).

Pre-1.0 rules:
- **Minor** (0.x.0): new agents/skills, new frontmatter fields, significant behavior changes
- **Patch** (0.0.x): bug fixes, doc corrections, minor wording changes

## Required Skills (plugin-dev)

Before modifying plugin components, load the matching `plugin-dev` skill from [claude-plugins-official](https://github.com/anthropics/claude-plugins-official):

- Before modifying an **agent** → load `plugin-dev:agent-development`
- Before modifying a **skill** → load `plugin-dev:skill-development`
- Before modifying **hooks** → load `plugin-dev:hook-development`
- Before modifying **plugin structure or plugin.json** → load `plugin-dev:plugin-structure`
- After creating/modifying an agent → run `plugin-dev:agent-creator` or `plugin-dev:skill-reviewer` to validate
- After modifying plugin components → run `plugin-dev:plugin-validator` to check structure

## Temporary Files

Use `tmp/` (gitignored) for eval workspaces and transient artifacts.
