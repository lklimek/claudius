"""Role skills own policy; optional agent identities must load those skills."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
ROLE_SKILLS = (
    "architecture",
    "coding-best-practices",
    "grand-admiral",
    "review",
    "security-best-practices",
    "technical-writing",
    "product-design",
)
AGENT_ROLES = {
    "architect-nagatha": "architecture",
    "claudius": "grand-admiral",
    "developer-bilby": "coding-best-practices",
    "project-reviewer-adams": "review",
    "qa-engineer-marvin": "review",
    "security-engineer-smythe": "security-best-practices",
    "technical-writer-trillian": "technical-writing",
    "ux-designer-diziet": "product-design",
}
SKILL_LINK = re.compile(r"\]\(([^)#]+/SKILL\.md)(?:#[^)]*)?\)")


def _reachable_skills(path: Path, seen: set[Path] | None = None) -> set[Path]:
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return seen
    seen.add(path)
    for target in SKILL_LINK.findall(path.read_text(encoding="utf-8")):
        linked = (path.parent / target).resolve()
        assert linked.is_file(), f"{path}: missing skill dependency {target}"
        _reachable_skills(linked, seen)
    return seen


@pytest.mark.parametrize("name", ROLE_SKILLS)
def test_role_skill_loads_coding_best_practices(name: str) -> None:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"Role instructions are not discoverable: {path}"
    assert SKILLS_DIR / "coding-best-practices" / "SKILL.md" in _reachable_skills(path)


@pytest.mark.parametrize("name,role", AGENT_ROLES.items())
def test_agent_identity_loads_role_skill(name: str, role: str) -> None:
    path = REPO_ROOT / "agents" / f"{name}.md"
    assert path.is_file(), f"Missing identity: {path}"
    front = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["name"] == name
    assert front["skills"] == [role]
    assert SKILLS_DIR / role / "SKILL.md" in _reachable_skills(path)
    assert SKILLS_DIR / "coding-best-practices" / "SKILL.md" in _reachable_skills(path)


@pytest.mark.parametrize("path", sorted((REPO_ROOT / "agents").glob("*.md")))
def test_agent_metadata_only_defines_identity_and_skill_loading(path: Path) -> None:
    front = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert front.keys() <= {"name", "description", "model", "color", "skills"}
    assert front["model"] == "inherit"


@pytest.mark.parametrize("path", sorted(SKILLS_DIR.glob("*/SKILL.md")))
def test_skills_do_not_require_agent_frontmatter(path: Path) -> None:
    front = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    agent_fields = {"agent", "skills", "tools", "mcpServers", "memory"}
    assert not (agent_fields & front.keys()), f"{path}: agent-only metadata"
