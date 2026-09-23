"""Regression guard: headless-CI review skills grant plugin scripts via anchored rules only.

Claude Code substitutes ``${CLAUDE_PLUGIN_ROOT}`` in a plugin skill's body AND in its
``allowed-tools`` Bash rules, and matches Bash rules as a literal prefix: a body
invocation spelled ``${CLAUDE_SKILL_DIR}/../../scripts/x.py`` is NOT normalized and never
matches an anchored ``${CLAUDE_PLUGIN_ROOT}/scripts/x.py`` rule. So the rule and every
body invocation must change in lockstep — this test pins that, plus "no unanchored
``*x.py *`` script globs" (they match the same name anywhere on disk).
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHORED_SKILLS = ("grumpy-review", "review-pr", "check-pr-comments")
ROOT = "${CLAUDE_PLUGIN_ROOT}/scripts/"
SCRIPT_INVOCATION = re.compile(
    r"(?:python3 )?\$\{CLAUDE_(?:SKILL_DIR|PLUGIN_ROOT)\}[^\s`\"]*?scripts/[\w.-]+\.(?:py|sh)[^`\n]*"
)


def _split(path: Path) -> tuple[dict, str]:
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(front), body


def _bash_rules(front: dict) -> list[str]:
    tools = front.get("allowed-tools", "")
    items = tools if isinstance(tools, list) else re.split(r",\s*(?![^()]*\))", tools)
    return [t.strip()[5:-1] for t in items if t.strip().startswith("Bash(")]


@pytest.mark.parametrize("skill", ANCHORED_SKILLS)
def test_script_rules_are_anchored(skill: str) -> None:
    front, _ = _split(REPO_ROOT / "skills" / skill / "SKILL.md")
    for rule in _bash_rules(front):
        if re.search(r"\.(py|sh)\b", rule):
            assert ROOT in rule and not rule.startswith("*"), (
                f"{skill}: unanchored {rule!r}"
            )
            script = rule.split(ROOT, 1)[1].split()[0]
            assert (REPO_ROOT / "scripts" / script).is_file(), (
                f"{skill}: missing {script}"
            )


@pytest.mark.parametrize("skill", ANCHORED_SKILLS)
def test_body_invocations_match_a_rule(skill: str) -> None:
    front, body = _split(REPO_ROOT / "skills" / skill / "SKILL.md")
    rules = _bash_rules(front)
    invocations = [m.group(0).strip() for m in SCRIPT_INVOCATION.finditer(body)]
    assert invocations, f"{skill}: no script invocations found — regex broken?"
    for cmd in invocations:
        assert "CLAUDE_SKILL_DIR" not in cmd, (
            f"{skill}: use {ROOT}, not SKILL_DIR/../..: {cmd!r}"
        )
        assert any(fnmatchcase(cmd, r) for r in rules), (
            f"{skill}: no allowed-tools rule matches {cmd!r}"
        )
