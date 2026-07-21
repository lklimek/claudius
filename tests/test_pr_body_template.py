"""Regression guard: the canonical PR-body template lives in one external file.

The literal skeleton lives ONLY in `skills/git-and-github/references/pr-body-template.md`;
`git-and-github/SKILL.md` and `push/SKILL.md` must reference it, not inline a duplicate.
This test pins the template's heading set/ordering (`TL;DR` -> `## User story` ->
`## Scenario` (`### Base flow` / `### Actual behavior` / `### Expected behavior`) ->
`## Detailed discussion`) and guards against the skeleton drifting back into the skills.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_GITHUB = REPO_ROOT / "skills" / "git-and-github" / "SKILL.md"
PUSH = REPO_ROOT / "skills" / "push" / "SKILL.md"
TEMPLATE = REPO_ROOT / "skills" / "git-and-github" / "references" / "pr-body-template.md"

USER_STORY = "## User story"
SCENARIO = "## Scenario"
DETAILED = "## Detailed discussion"

SKELETON_HEADINGS = (
    "**TL;DR:**",
    USER_STORY,
    SCENARIO,
    "### Base flow",
    "### Actual behavior",
    "### Expected behavior",
    DETAILED,
    "### What was done",
    "### Testing",
    "### Breaking changes",
    "### Checklist",
    "### Attribution",
    "### Prior work",
)


def test_template_has_required_headings() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for heading in SKELETON_HEADINGS:
        assert heading in text, f"{TEMPLATE}: missing '{heading}'"


def test_template_sections_are_ordered() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    tldr = text.index("**TL;DR:**")
    user_story = text.index(USER_STORY)
    scenario = text.index(SCENARIO)
    base_flow = text.index("### Base flow")
    actual = text.index("### Actual behavior")
    expected = text.index("### Expected behavior")
    detailed = text.index(DETAILED)
    prior_work = text.index("### Prior work")
    assert tldr < user_story < scenario < detailed, (
        f"{TEMPLATE}: sections must appear in order TL;DR -> User story -> Scenario -> Detailed discussion"
    )
    assert scenario < base_flow < actual < expected < detailed, (
        f"{TEMPLATE}: 'Scenario' sub-sections must appear in order "
        "Base flow -> Actual behavior -> Expected behavior, before 'Detailed discussion'"
    )
    assert prior_work == max(text.index(h) for h in SKELETON_HEADINGS), (
        f"{TEMPLATE}: 'Prior work' must be the last section in the skeleton"
    )


def _heading_at_line_start(text: str, heading: str) -> bool:
    """True if `heading` appears as its own line (a real heading), not just quoted in prose."""
    return re.search(r"^" + re.escape(heading), text, re.MULTILINE) is not None


def test_skill_references_template_without_inlining_it() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    assert "references/pr-body-template.md" in text, (
        f"{GIT_GITHUB}: must link to references/pr-body-template.md"
    )
    for heading in SKELETON_HEADINGS:
        assert not _heading_at_line_start(text, heading), (
            f"{GIT_GITHUB}: must not inline a duplicate '{heading}' heading — delegate to pr-body-template.md"
        )


def test_skill_demands_plain_language_for_user_facing_sections() -> None:
    """TL;DR / User story / Scenario must be scoped to plain, user-observable info."""
    text = GIT_GITHUB.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "plain language" in lowered or "plain-language" in lowered, (
        f"{GIT_GITHUB}: must require plain language in the user-facing PR sections"
    )
    assert "user-observable" in lowered, (
        f"{GIT_GITHUB}: must scope user-facing PR sections to user-observable behavior"
    )


def test_push_references_skeleton_without_inlining_it() -> None:
    text = PUSH.read_text(encoding="utf-8")
    assert "git-and-github" in text, (
        f"{PUSH}: must delegate to git-and-github for the template"
    )
    for heading in (USER_STORY, SCENARIO, DETAILED):
        assert not _heading_at_line_start(text, heading), (
            f"{PUSH}: must not inline a duplicate '{heading}' template — delegate to git-and-github"
        )
