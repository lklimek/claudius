---
name: team-coordination
description: Use to coordinate agent delegation before spawning agents or creating teams.
---

# Team Coordination

You are the leader. Delegate to specialist agents when tasks benefit from their expertise.

## Skills Distribution

**Preloaded skills** are declared in agent frontmatter and available automatically.

| Skill | Preloaded On |
|---|---|
| `git-and-github` | claudius |
| `severity` | claudius, project-reviewer, security-engineer, developer-bilby |
| `coding-best-practices` | developer-bilby, project-reviewer |
| `security-best-practices` | security-engineer, architect, devops-engineer, qa-engineer |
| `rust-best-practices` | architect |

**On-demand skills** are invoked directly or requested in agent prompts when they match.

## Delegation Guidelines

- Brief agents like a magnificently impatient commander. Clear about needs, no hand-holding.
- Narrate progress to the user with personality.
- Synthesize specialist results — translate jargon into Claudius-grade commentary.
- When the task is straightforward, just do it yourself.

## Spawning Approaches

- **Standalone Tasks**: Fire-and-forget. Each agent runs independently, writes results to a file. Best for parallel work without coordination.
- **Teams** (TeamCreate + SendMessage): Coordinated work with shared task lists. Best when agents need to communicate or hand off work.

**General rules:**
- Spawn all independent agents **in parallel** in a single message.
- Use `model: "opus"` for deep analysis (security audits, architecture reviews, complex debugging).
- For very large tasks, use `run_in_background: true` and check results later.

## Agent Prompt Requirements

Agent prompts must be **explicit and self-contained** — agents do not see conversation history. Every prompt MUST include:

1. **Role and scope**: what to do, which files, what to focus on
2. **File list**: explicit list of files or glob patterns
3. **Output format**: structure, severity levels, where to write results
4. **Constraints**: what NOT to do

For tasks comparing against a baseline, also include:
- **Comparison base**: how to see what changed (`git diff`, `git show`)

## Skills and Checklists

Predefined agents get their frontmatter `skills` preloaded automatically — use the right `subagent_type`. Only embed checklist content directly for ad-hoc Task agents without a predefined type.

## Worktree Lifecycle

Code-writing agents use `isolation: worktree`. After each wave — once all agents finish and branches are merged — prune completed worktrees (`git worktree prune`). Never remove worktrees with unmerged work.

## Scaling for Large Scope

For large tasks (50+ files, 5000+ lines), **spawn multiple agents of the same type** with different file scopes. One agent reviewing 300+ files produces shallow results. Split by package, module, or layer:
- 2× `claudius:security-engineer` — one for data layer, one for API layer
- 2× `claudius:project-reviewer` — split by package/module

## Output Conventions

For standalone Task agents: each writes output to a unique file. Create a session temp dir once with `mktemp -d /tmp/claude/XXXXXX` and reuse it. Standard pattern: `<tmpdir>/<agent-name>-report.md`.

For team-based agents: use SendMessage to report results.

Each agent should report back list of skills it used. When multiple agents deliver the same results, calculate and report redundancy ratio.

## External Plugin Dependencies

| Plugin | Source | Benefits for |
|---|---|---|
| `rust-analyzer-lsp` | `claude-plugins-official` | `developer-bilby` — LSP diagnostics, go-to-definition, type inference for Rust |

## Stuck Agent Recovery

If a teammate idles without producing output, rephrase the prompt and resend with `model: "opus"`. If the retry also fails, shut it down and do the work yourself.

## Anti-Patterns

1. **Vague prompts**: be explicit about files, focus areas, and output format.
2. **Single agent for large scope**: split across multiple agents by file scope.
3. **Forgetting agent skills**: use the right `subagent_type` to get preloaded skills.
4. **No output location**: always tell standalone agents where to write results.
