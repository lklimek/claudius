# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Claudius** is a Claude Code plugin published at [github.com/lklimek/claudius](https://github.com/lklimek/claudius). It provides a collection of reusable agents and skills for software development workflows.

## Repository Structure

```
agents/          # Agent definitions (Markdown files with YAML frontmatter)
skills/          # Skill definitions (directories, each containing SKILL.md + optional resources)
```

### Agents

Each agent is a single `.md` file with YAML frontmatter defining:

```yaml
---
name: agent-name
description: "When to use this agent."
tools: Read, Grep, Glob, Bash   # available tools (omit Edit/Write for read-only agents)
model: inherit                   # or a specific model
---
```

The body contains the agent's system prompt: role definition, instructions, and behavioral rules.

### Skills

Each skill is a directory containing:

- `SKILL.md` — main skill definition with YAML frontmatter (`name`, `description`) and instructions
- Optional subdirectories for supporting resources (e.g., `references/`, `scripts/`)

```yaml
---
name: skill-name
description: When and how this skill should be invoked.
---
```

## Conventions

- Agent names use lowercase kebab-case (e.g., `security-engineer.md`)
- Skill directory names match the skill name in kebab-case
- Agents and skills are self-contained — each file/directory should work independently
- Descriptions in frontmatter must clearly state **when** the agent/skill should be used, not just what it does
- Tools listed in agent frontmatter define the agent's capability boundary; prefer minimal tool sets (read-only agents should not have Edit/Write)

## Installation

Agents and skills from this repo are installed into `~/.claude/agents/` and `~/.claude/skills/` respectively.
