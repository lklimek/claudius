"""Regression guard: the canonical PR-body template leads with a plain-language summary.

PR descriptions are owned by ONE skill (`git-and-github`); `push` delegates to it.
This test pins the contract so a refactor can't silently demote the human-readable
sections below implementation detail: `git-and-github/SKILL.md` must define, in
order, `TL;DR` -> `## User story` -> `## Scenario` (with `### Base flow`,
`### Actual behavior`, `### Expected behavior`) -> `## Detailed discussion`, and
`push/SKILL.md` must reference that skeleton rather than inlining a duplicate.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_GITHUB = REPO_ROOT / "skills" / "git-and-github" / "SKILL.md"
PUSH = REPO_ROOT / "skills" / "push" / "SKILL.md"

USER_STORY = "## User story"
SCENARIO = "## Scenario"
DETAILED = "## Detailed discussion"


def test_git_github_has_required_headings() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    for heading in (
        "**TL;DR:**",
        USER_STORY,
        SCENARIO,
        "### Base flow",
        "### Actual behavior",
        "### Expected behavior",
        DETAILED,
    ):
        assert heading in text, f"{GIT_GITHUB}: missing '{heading}' in PR-body template"


def test_sections_are_ordered() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    tldr = text.index("**TL;DR:**")
    user_story = text.index(USER_STORY)
    scenario = text.index(SCENARIO)
    base_flow = text.index("### Base flow")
    actual = text.index("### Actual behavior")
    expected = text.index("### Expected behavior")
    detailed = text.index(DETAILED)
    assert tldr < user_story < scenario < detailed, (
        f"{GIT_GITHUB}: sections must appear in order TL;DR -> User story -> "
        "Scenario -> Detailed discussion"
    )
    assert scenario < base_flow < actual < expected < detailed, (
        f"{GIT_GITHUB}: 'Scenario' sub-sections must appear in order "
        "Base flow -> Actual behavior -> Expected behavior, before 'Detailed discussion'"
    )


def test_user_facing_sections_demand_plain_language() -> None:
    """TL;DR / User story / Scenario must be scoped to plain, user-observable info."""
    text = GIT_GITHUB.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "plain language" in lowered or "plain-language" in lowered, (
        f"{GIT_GITHUB}: template must require plain language in the user-facing sections"
    )
    assert "user-observable" in lowered, (
        f"{GIT_GITHUB}: template must scope user-facing sections to user-observable behavior"
    )


def test_detailed_discussion_holds_implementation_content() -> None:
    """Former 'Why this PR exists' content (What was done/Testing/etc.) now lives under Detailed discussion."""
    text = GIT_GITHUB.read_text(encoding="utf-8")
    detailed = text.index(DETAILED)
    for sub_heading in ("### What was done", "### Testing", "### Breaking changes", "### Checklist", "### Attribution"):
        pos = text.index(sub_heading)
        assert pos > detailed, (
            f"{GIT_GITHUB}: '{sub_heading}' must be nested under '{DETAILED}'"
        )


def test_push_references_skeleton_without_inlining_it() -> None:
    text = PUSH.read_text(encoding="utf-8")
    assert "git-and-github" in text, (
        f"{PUSH}: must delegate to git-and-github for the template"
    )
    # No duplicated skeleton: push references the sections, it doesn't redefine the headings.
    for heading in (USER_STORY, SCENARIO, DETAILED):
        assert heading not in text, (
            f"{PUSH}: must not inline a duplicate '{heading}' template — delegate to git-and-github"
        )
