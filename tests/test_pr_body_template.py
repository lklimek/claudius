"""Regression guard: the canonical PR-body template must lead with "Why this PR exists".

PR descriptions are owned by ONE skill (`git-and-github`); `push` delegates to it.
This test pins the contract so a refactor can't silently demote the rationale section
below the mechanics: `git-and-github/SKILL.md` must define a "Why this PR exists"
heading positioned AHEAD of the "What was done"/"Testing" sections, and `push/SKILL.md`
must reference it rather than inlining a duplicate template.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT_GITHUB = REPO_ROOT / "skills" / "git-and-github" / "SKILL.md"
PUSH = REPO_ROOT / "skills" / "push" / "SKILL.md"

WHY = "Why this PR exists"


def test_git_github_has_why_section() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    assert f"## {WHY}" in text, (
        f"{GIT_GITHUB}: missing '## {WHY}' heading in PR-body template"
    )


def test_why_section_leads_what_and_testing() -> None:
    text = GIT_GITHUB.read_text(encoding="utf-8")
    why = text.index(f"## {WHY}")
    what = text.index("## What was done")
    testing = text.index("## Testing")
    assert why < what, f"{GIT_GITHUB}: '{WHY}' must precede 'What was done'"
    assert why < testing, f"{GIT_GITHUB}: '{WHY}' must precede 'Testing'"


def test_why_section_demands_reproduction_and_blocking() -> None:
    """The skeleton must prompt for a concrete repro/threat scenario and blocking relationship."""
    text = GIT_GITHUB.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "reproduction" in lowered or "threat scenario" in lowered, (
        f"{GIT_GITHUB}: '{WHY}' skeleton must ask for a reproduction or threat scenario"
    )
    assert "blocking" in lowered, (
        f"{GIT_GITHUB}: '{WHY}' skeleton must ask for the blocking relationship"
    )


def test_push_references_why_without_inlining_template() -> None:
    text = PUSH.read_text(encoding="utf-8")
    assert WHY in text, f"{PUSH}: must reference the '{WHY}' section"
    assert "git-and-github" in text, (
        f"{PUSH}: must delegate to git-and-github for the template"
    )
    # No duplicated skeleton: push references the section, it doesn't redefine the heading.
    assert f"## {WHY}" not in text, (
        f"{PUSH}: must not inline a duplicate '## {WHY}' template — delegate to git-and-github"
    )
