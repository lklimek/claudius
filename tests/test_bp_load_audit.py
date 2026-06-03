"""BP-load audit: every coding/reviewing agent must declare `coding-best-practices`.

Cross-Cutting Rules (no tombstones, present-state comments, verify-before-act,
minimize code, etc.) only bind an agent when it preloads `coding-best-practices`.
Reviewer agents that omit the skill silently skip those rules, so audits hinge
on this regression guard.

The curated list below is the project-level contract — adding a new
coding/reviewing agent? Add it here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

# Agents that write, edit, or review code. Each MUST load `coding-best-practices`
# so its Cross-Cutting Rules govern every action and finding.
BP_REQUIRED_AGENTS = [
    "architect-nagatha",
    "claudius",
    "developer-bilby",
    "project-reviewer-adams",
    "qa-engineer-marvin",
    "security-engineer-smythe",
    "technical-writer-trillian",
    "ux-designer-diziet",
]


def _load_frontmatter(agent_name: str) -> dict:
    path = AGENTS_DIR / f"{agent_name}.md"
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path}: no `---` frontmatter delimiters found"
    data = yaml.safe_load(parts[1])
    assert isinstance(data, dict), f"{path}: frontmatter did not parse to a dict"
    return data


@pytest.mark.parametrize("agent_name", BP_REQUIRED_AGENTS)
def test_agent_loads_coding_best_practices(agent_name: str) -> None:
    fm = _load_frontmatter(agent_name)
    skills = fm.get("skills", [])
    assert isinstance(
        skills, list
    ), f"agents/{agent_name}.md: `skills` field must be a list, got {type(skills).__name__}"
    assert "coding-best-practices" in skills, (
        f"agents/{agent_name}.md: missing `coding-best-practices` in `skills` frontmatter "
        f"(found: {skills}). Reviewer/coder agents must preload BP so its "
        f"Cross-Cutting Rules govern every finding."
    )
