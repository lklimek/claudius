"""Regression guard: the canonical issue-body template lives in one external file.

Mirrors `test_pr_body_template.py`: the literal skeleton lives ONLY in
`skills/git-and-github/references/issue-body-template.md`; `git-and-github/SKILL.md`
must reference it (§Issues), not inline a duplicate. Pins the template's heading
set/ordering — same plain-language-first shape as the PR-body template.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_GITHUB = REPO_ROOT / "skills" / "git-and-github" / "SKILL.md"
TEMPLATE = REPO_ROOT / "skills" / "git-and-github" / "references" / "issue-body-template.md"

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
    attribution = text.index("### Attribution")
    prior_work = text.index("### Prior work")
    assert tldr < user_story < scenario < detailed, (
        f"{TEMPLATE}: sections must appear in order TL;DR -> User story -> Scenario -> Detailed discussion"
    )
    assert scenario < base_flow < actual < expected < detailed, (
        f"{TEMPLATE}: 'Scenario' sub-sections must appear in order "
        "Base flow -> Actual behavior -> Expected behavior, before 'Detailed discussion'"
    )
    assert detailed < attribution, (
        f"{TEMPLATE}: 'Attribution' must be nested under 'Detailed discussion'"
    )
    assert prior_work == max(text.index(h) for h in SKELETON_HEADINGS), (
        f"{TEMPLATE}: 'Prior work' must be the last section in the skeleton"
    )


def test_skill_references_template_without_inlining_it() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    assert "references/issue-body-template.md" in text, (
        f"{GIT_GITHUB}: §Issues must link to references/issue-body-template.md"
    )


def test_skill_issues_section_scoped_to_shared_template() -> None:
    """§Issues should point at the shared skeleton, not restate a bespoke one."""
    text = GIT_GITHUB.read_text(encoding="utf-8")
    issues_heading = text.index("### Issues")
    issues_section = text[issues_heading:]
    for heading in SKELETON_HEADINGS:
        assert re.search(r"^" + re.escape(heading), issues_section, re.MULTILINE) is None, (
            f"{GIT_GITHUB}: §Issues must not inline a duplicate '{heading}' heading — delegate to issue-body-template.md"
        )
