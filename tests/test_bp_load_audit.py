"""Role skills own policy; agent identities preload and invoke them.

Claude Code resolves a bare skill name to a bundled command first (`/review` is the
bundled code review), applies `skills:` only to Agent-tool subagents (not teammates
or `--agent` main sessions), and cannot resolve relative links from an agent body.
Identities therefore preload namespaced skills AND tell the model to invoke them
through the Skill tool.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
AGENTS_DIR = REPO_ROOT / "agents"
ROLE_SKILLS = (
    "architecture",
    "coding-best-practices",
    "grand-admiral",
    "review-changes",
    "security-best-practices",
    "technical-writing",
    "product-design",
)
AGENT_ROLES = {
    "architect-nagatha": "architecture",
    "claudius": "grand-admiral",
    "developer-bilby": "coding-best-practices",
    "project-reviewer-adams": "review-changes",
    "qa-engineer-marvin": "review-changes",
    "security-engineer-smythe": "security-best-practices",
    "technical-writer-trillian": "technical-writing",
    "ux-designer-diziet": "product-design",
}
AGENT_MODELS = {
    "architect-nagatha": "opus",
    "claudius": "opus",
    "developer-bilby": "opus",
    "project-reviewer-adams": "opus",
    "qa-engineer-marvin": "sonnet",
    "security-engineer-smythe": "opus",
    "technical-writer-trillian": "sonnet",
    "ux-designer-diziet": "opus",
}
FINDING_PRODUCERS = (
    "project-reviewer-adams",
    "qa-engineer-marvin",
    "security-engineer-smythe",
)
# Review/design roles that must not modify the reviewed code.
READ_ONLY = ("architect-nagatha", "project-reviewer-adams", "security-engineer-smythe")
# Leaf passes: dispatching peers is the coordinator's job.
LEAF = FINDING_PRODUCERS
# https://code.claude.com/docs/en/sub-agents — supported `color` values.
DOCUMENTED_COLORS = {
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "orange",
    "pink",
    "cyan",
}
ALLOWED_KEYS = {"name", "description", "model", "color", "skills", "tools"}
SKILL_TOOL_REF = re.compile(r"`claudius:([a-z0-9-]+)`")
SKILL_LINK = re.compile(r"\]\(([^)#]+/SKILL\.md)(?:#[^)]*)?\)")


def _front(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


def _body(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---", 2)[2]


def _agent(name: str) -> Path:
    path = AGENTS_DIR / f"{name}.md"
    assert path.is_file(), f"Missing identity: {path}"
    return path


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


def test_agent_roster_is_complete() -> None:
    assert {p.stem for p in AGENTS_DIR.glob("*.md")} == set(AGENT_ROLES)


@pytest.mark.parametrize("name,role", AGENT_ROLES.items())
def test_agent_preloads_namespaced_role_skills(name: str, role: str) -> None:
    front = _front(_agent(name))
    assert front["name"] == name
    skills = front["skills"]
    assert skills[0] == f"claudius:{role}", "role skill must come first"
    assert "claudius:coding-best-practices" in skills
    if name in FINDING_PRODUCERS:
        assert {"claudius:severity", "claudius:report-format"} <= set(skills)
    for skill in skills:
        assert skill.startswith("claudius:"), f"{name}: bare skill name {skill!r}"
        target = SKILLS_DIR / skill.removeprefix("claudius:") / "SKILL.md"
        assert target.is_file(), f"{name}: preloads missing skill {skill}"


@pytest.mark.parametrize("name", AGENT_ROLES)
def test_agent_body_invokes_preloaded_skills_via_skill_tool(name: str) -> None:
    path = _agent(name)
    body = _body(path)
    assert "Skill tool" in body, f"{name}: body must instruct Skill-tool invocation"
    assert "../skills/" not in body and "SKILL.md" not in body, (
        f"{name}: relative skill links do not resolve at runtime"
    )
    named = set(SKILL_TOOL_REF.findall(body))
    preloaded = {s.removeprefix("claudius:") for s in _front(path)["skills"]}
    assert preloaded <= named, f"{name}: body omits {sorted(preloaded - named)}"
    for skill in named:
        assert (SKILLS_DIR / skill / "SKILL.md").is_file(), f"{name}: {skill} missing"


@pytest.mark.parametrize("name,model", AGENT_MODELS.items())
def test_agent_model(name: str, model: str) -> None:
    assert _front(_agent(name))["model"] == model


@pytest.mark.parametrize("name", AGENT_ROLES)
def test_agent_metadata_keys_and_description(name: str) -> None:
    front = _front(_agent(name))
    extra = front.keys() - ALLOWED_KEYS
    assert not extra, f"{name}: unexpected keys {sorted(extra)}"
    assert front["description"].startswith("Use "), (
        f"{name}: description must state when to use the agent"
    )


@pytest.mark.parametrize("name", AGENT_ROLES)
def test_agent_tools(name: str) -> None:
    tools = _front(_agent(name)).get("tools")
    if name == "claudius":
        assert tools is None, "the coordinator stays unrestricted"
        return
    assert isinstance(tools, list) and {"Read", "Skill", "Write"} <= set(tools)
    if name in READ_ONLY:
        assert not {"Edit", "NotebookEdit"} & set(tools), f"{name}: read-only role"
    if name in LEAF:
        assert not {"Agent", "Task"} & set(tools), f"{name}: leaf pass dispatches"


def test_agent_colors_documented_and_distinct() -> None:
    colors = [_front(_agent(n))["color"] for n in AGENT_ROLES]
    assert set(colors) <= DOCUMENTED_COLORS, sorted(set(colors) - DOCUMENTED_COLORS)
    assert len(set(colors)) == len(colors), f"duplicate colors: {colors}"


@pytest.mark.parametrize("path", sorted(SKILLS_DIR.glob("*/SKILL.md")))
def test_skills_do_not_require_agent_frontmatter(path: Path) -> None:
    front = _front(path)
    agent_fields = {"skills", "tools", "mcpServers", "memory"}
    assert not (agent_fields & front.keys()), f"{path}: agent-only metadata"
    if "agent" in front:
        assert front.get("context") == "fork", f"{path}: `agent` needs context: fork"


def test_review_dependency_runs_forked_in_foreground() -> None:
    front = _front(SKILLS_DIR / "review-dependency" / "SKILL.md")
    assert front.get("context") == "fork"
    assert front.get("background") is False, "the invoker must wait for the report"
