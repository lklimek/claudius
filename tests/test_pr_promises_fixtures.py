"""Pass C promise-verification fixture sanity tests.

The `tests/fixtures/pr-promises/*.md` files document the expected behaviour of
the Pass C audit axes (title/diff alignment, body summary/diff alignment,
out-of-scope enforcement). Without an executable check, the fixtures and the
SKILL.md heuristics they document can drift apart silently.

These tests verify the **structural contract** the fixtures advertise:
required sections, well-formed `<!-- expected: { ... } -->` annotation, and
internal consistency between the documented `expected_finding_count` /
per-axis hints and the fixture body. They do NOT execute Pass C itself —
that requires an LLM. They DO guarantee the fixtures stay loadable and
self-describing for any harness that wants to drive Pass C against them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pr-promises"

EXPECTED_BLOCK_RE = re.compile(
    r"<!--\s*expected:\s*(?P<json>\{.*?\})\s*-->",
    re.DOTALL,
)

# Per-axis hint values the fixture annotation may legally take. The fixtures
# describe the SHAPE of the mismatch, not the specific copy — so the test
# pins the vocabulary, not the wording.
TITLE_ALIGNMENT_VALUES = {"aligned", "off_target", "vague"}
SUMMARY_ALIGNMENT_VALUES = {"aligned", "missing_claim", "partial", "undocumented"}
OUT_OF_SCOPE_VALUES = {"aligned", "scope_creep"}


def _load_fixture(name: str) -> tuple[str, dict]:
    """Return (raw_text, parsed_expected_block) for a named fixture."""
    path = FIXTURES_DIR / name
    text = path.read_text(encoding="utf-8")
    match = EXPECTED_BLOCK_RE.search(text)
    assert match is not None, f"{name}: missing `<!-- expected: {{...}} -->` block"
    try:
        expected = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:  # pragma: no cover - assertion text shows it
        pytest.fail(f"{name}: expected block is not valid JSON: {exc}")
    return text, expected


def _assert_required_sections(name: str, text: str, sections: list[str]) -> None:
    """Each section header listed in `required_sections` must appear at column 0."""
    for header in sections:
        # Use a line-anchored regex so a header inside a code fence still counts —
        # the fixture format intentionally puts `## PR Body` / `## Out of scope`
        # at column 0 of the document itself, separate from the code-fenced PR
        # body content. Both should be present.
        pattern = re.compile(rf"^{re.escape(header)}(?:$|\s)", re.MULTILINE)
        assert pattern.search(text), f"{name}: required section missing: {header!r}"


# ---------------------------------------------------------------------------
# Fixture directory exists and is populated
# ---------------------------------------------------------------------------
def test_pr_promises_fixtures_dir_present():
    assert FIXTURES_DIR.is_dir(), f"Expected fixtures dir at {FIXTURES_DIR}"
    md_files = sorted(p.name for p in FIXTURES_DIR.glob("*.md"))
    assert "synthetic-mismatched.md" in md_files
    assert "synthetic-clean.md" in md_files


# ---------------------------------------------------------------------------
# synthetic-mismatched.md — drives all 3 axes, expects 3 findings
# ---------------------------------------------------------------------------
def test_mismatched_fixture_expected_block_well_formed():
    _, expected = _load_fixture("synthetic-mismatched.md")
    assert expected["expected_finding_count"] == 3
    assert expected["title_alignment"] in TITLE_ALIGNMENT_VALUES
    assert expected["summary_alignment"] in SUMMARY_ALIGNMENT_VALUES
    assert expected["out_of_scope"] in OUT_OF_SCOPE_VALUES


def test_mismatched_fixture_documents_each_axis():
    """Per-axis hints must each describe a mismatch (not 'aligned') since the
    fixture's purpose is to drive ALL three triggers."""
    _, expected = _load_fixture("synthetic-mismatched.md")
    assert expected["title_alignment"] != "aligned"
    assert expected["summary_alignment"] != "aligned"
    assert expected["out_of_scope"] != "aligned"


def test_mismatched_fixture_required_sections_present():
    text, expected = _load_fixture("synthetic-mismatched.md")
    _assert_required_sections(
        "synthetic-mismatched.md", text, expected["required_sections"]
    )


def test_mismatched_fixture_out_of_scope_section_actually_lists_an_item():
    """The annotation claims `out_of_scope: scope_creep` — the body must
    therefore contain an `## Out of scope` section with at least one bullet,
    so a Pass C runner has something to evaluate against the diff."""
    text, expected = _load_fixture("synthetic-mismatched.md")
    if expected["out_of_scope"] == "scope_creep":
        # Match the section header AND at least one bullet on a subsequent line.
        oos = re.search(
            r"^## Out of scope\b.*?^[-*] ",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert oos is not None, (
            "Annotation claims scope_creep but fixture has no `## Out of scope` "
            "bullet for the diff to drift from."
        )


# ---------------------------------------------------------------------------
# synthetic-clean.md — aligned across all axes, expects 0 findings
# ---------------------------------------------------------------------------
def test_clean_fixture_expected_block_well_formed():
    _, expected = _load_fixture("synthetic-clean.md")
    assert expected["expected_finding_count"] == 0
    assert expected["title_alignment"] == "aligned"
    assert expected["summary_alignment"] == "aligned"
    assert expected["out_of_scope"] == "aligned"


def test_clean_fixture_required_sections_present():
    text, expected = _load_fixture("synthetic-clean.md")
    _assert_required_sections("synthetic-clean.md", text, expected["required_sections"])


# ---------------------------------------------------------------------------
# Cross-fixture invariants
# ---------------------------------------------------------------------------
def test_all_fixtures_carry_expected_annotation():
    """Any future `.md` fixture added to the dir must follow the same
    self-describing convention."""
    for path in FIXTURES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        match = EXPECTED_BLOCK_RE.search(text)
        assert match is not None, (
            f"{path.name}: every pr-promises fixture must end with an "
            "`<!-- expected: {...} -->` annotation block."
        )
        # And the JSON must parse.
        json.loads(match.group("json"))
