# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claudius** is a Claude Code plugin published at [github.com/lklimek/claudius](https://github.com/lklimek/claudius). It provides a collection of reusable agents and skills for software development workflows. Licensed under GPL-3.0.

## Repository Structure

```
.claude-plugin/
  plugin.json      # Plugin manifest (name, version, description, author, license)
agents/            # Agent definitions (Markdown files with YAML frontmatter)
skills/            # Skill definitions (directories, each containing SKILL.md + optional resources)
```

## Plugin Manifest

`.claude-plugin/plugin.json` — only `name` is required. Component directories (`agents/`, `skills/`) are auto-discovered at the plugin root. Custom paths in manifest supplement (not replace) defaults.

## Agents

Each agent is a single `.md` file with YAML frontmatter:

```yaml
---
name: agent-name
description: "When to use this agent."
tools: Read, Grep, Glob, Bash   # available tools (omit Edit/Write for read-only agents)
model: inherit                   # inherit | sonnet | opus | haiku
---
```

The body contains the agent's system prompt: role definition, instructions, and behavioral rules.

Additional frontmatter fields: `disallowedTools`, `permissionMode`, `maxTurns`, `skills` (preloaded), `mcpServers`, `hooks`, `memory` (user|project|local), `background`, `isolation` (worktree).

## Skills

Each skill is a directory containing:

- `SKILL.md` — main skill definition with YAML frontmatter (`name`, `description`) and instructions
- Optional subdirectories for supporting resources (e.g., `references/`, `scripts/`)

```yaml
---
name: skill-name
description: When and how this skill should be invoked.
---
```

Additional frontmatter fields: `argument-hint`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `context` (fork), `agent`, `hooks`.

String substitutions in skill body: `$ARGUMENTS`, `$0`/`$1`/etc., `${CLAUDE_SESSION_ID}`, `` !`command` `` (dynamic injection).

## Conventions

- Agent names use lowercase kebab-case (e.g., `security-engineer.md`)
- Skill directory names match the skill name in kebab-case
- Agents and skills are self-contained — each file/directory should work independently
- Descriptions in frontmatter must clearly state **when** the agent/skill should be used, not just what it does
- Tools listed in agent frontmatter define the agent's capability boundary; prefer minimal tool sets (read-only agents should not have Edit/Write)

## Development

Test the plugin locally without installing:

```bash
claude --plugin-dir /home/ubuntu/git/claudius
```

Validate the plugin manifest:

```bash
claude plugin validate .
```
