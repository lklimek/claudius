"""Doc-regression tests for review-pr Pass C v1.1 (TODOs 8c17d019 + 4463333d).

Two flavours of test live here:

1. **Grep-assert** that ``skills/review-pr/SKILL.md`` still documents each Pass C
   v1.1 rule. These pin the *wording* so a future SKILL edit can't silently drop
   a rule without a failing test.
2. **Parser-mirror** that re-implements the documented fenced-body unwrap exactly
   as the SKILL describes and checks that, against a fully-fenced fixture, the
   unwrap exposes the ``## Summary`` header that the column-0 regex would
   otherwise miss. Mirrors how ``tests/test_check_pr_comments_permalink.py``
   mirrors a documented producer rule.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "review-pr" / "SKILL.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pr-promises"

sys.path.insert(0, str(ROOT / "scripts"))
from severity_util import derive_finding_severity  # noqa: E402


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


_FLOAT_PAIR_RE = re.compile(r"`likelihood[≈=]([\d.]+), impact[≈=]([\d.]+)")
_LEGACY_FLOAT_PAIR_RE = re.compile(r"`risk[≈=][\d.]+, impact[≈=]")


def _documented_floats(anchor: str) -> dict[str, float]:
    """Return the likelihood/impact recipe documented alongside *anchor*.

    Reads the numbers out of the SKILL rather than restating them, so the
    tests below assert the real contract — the documented recipe derives the
    documented band — instead of pinning values that can drift apart from it.
    Loose on the separator (``=`` or ``≈``) and silent about ``relevance``,
    which no longer feeds the severity mean.

    Skips while the SKILL still carries the schema-v3 spelling, and fails when
    it carries neither: an unrecognizable recipe must not pass as "migrated".
    """
    for line in _skill_text().splitlines():
        if anchor not in line:
            continue
        match = _FLOAT_PAIR_RE.search(line)
        if match:
            return {
                "likelihood": float(match.group(1)),
                "impact": float(match.group(2)),
            }
        if _LEGACY_FLOAT_PAIR_RE.search(line):
            pytest.skip(
                f"{SKILL.name} still documents schema-v3 floats for {anchor!r}; "
                "this test activates when review-pr adopts likelihood/impact"
            )
    raise AssertionError(f"No likelihood/impact recipe documented for {anchor!r}")


# ---------------------------------------------------------------------------
# Grep-assert: documented rules survive
# ---------------------------------------------------------------------------
class TestSkillDocumentsPassCRules:
    def test_fenced_body_dedent_step(self):
        text = _skill_text()
        assert "Fenced-body unwrap" in text
        assert "dedent" in text

    def test_pr_body_unparseable_fallback(self):
        text = _skill_text()
        assert "PR body unparseable" in text
        assert "ONE low-confidence `pr_promises` LOW finding" in text

    def test_clean_pass_empty_findings_plus_info(self):
        text = _skill_text()
        assert "findings: []" in text
        assert "PR self-description verified" in text
        assert "never hand-write the integer `severity`" in text

    def test_undocumented_change_keyword_overlap(self):
        text = _skill_text()
        assert "keyword overlap" in text
        # The 50-LOC trigger is retained alongside the precise definition.
        assert "50 LOC" in text

    def test_summary_heading_precedence_order(self):
        text = _skill_text()
        assert "Summary-heading precedence" in text
        # Precedence order is documented as Summary > ### Summary > What changed.
        idx_h2 = text.find("`## Summary` > `### Summary` > `## What changed`")
        assert idx_h2 != -1

    def test_compound_title_majority_hits(self):
        text = _skill_text()
        assert "Majority-hits rule" in text

    def test_section_verdict_wiring(self):
        text = _skill_text()
        assert "finding_section.verdict" in text
        for kw in ("PASS", "FAIL", "NEEDS_REVIEW"):
            assert kw in text

    def test_language_cross_ref_not_hardcoded(self):
        text = _skill_text()
        # The hard-coded `language: "diff"` instruction is gone; a cross-ref to
        # report-format's code_snippets field reference takes its place.
        assert 'Use `language: "diff"`' not in text
        assert "report-format` §code_snippets" in text

    def test_report_type_pr_audit_documented(self):
        text = _skill_text()
        assert 'metadata.report_type: "pr_audit"' in text


# ---------------------------------------------------------------------------
# Band-derivation guard: the documented Pass C floats land in the documented
# bands. Pins the SKILL's "INFO" / "LOW" labels to severity_util's band table
# so the floats and bands can't drift apart again.
# ---------------------------------------------------------------------------
class TestPassCFloatsDeriveDocumentedBands:
    @pytest.mark.parametrize(
        "anchor,band",
        [
            ("PR self-description verified", 1),  # INFO
            ("PR body unparseable", 2),  # LOW
        ],
    )
    def test_documented_floats_derive_the_documented_band(self, anchor, band):
        assert derive_finding_severity(_documented_floats(anchor)) == band

    @pytest.mark.parametrize("relevance", [0.0, 0.5, 1.0])
    @pytest.mark.parametrize(
        "anchor", ["PR self-description verified", "PR body unparseable"]
    )
    def test_relevance_cannot_move_the_documented_band(self, anchor, relevance):
        """Whatever relevance Pass C assigns, the informational findings keep
        their band — relevance is out of the mean, so the old "Pass C scope
        exception" that forced it to 0.0 is no longer load-bearing."""
        floats = _documented_floats(anchor)
        assert derive_finding_severity(floats) == derive_finding_severity(
            {**floats, "relevance": relevance}
        )


# ---------------------------------------------------------------------------
# Parser-mirror: the documented fenced-body unwrap exposes ## Summary
# ---------------------------------------------------------------------------
SUMMARY_RE = re.compile(
    r"^##+\s+(?:Summary|What changed)\b", re.IGNORECASE | re.MULTILINE
)

_FENCE_RE = re.compile(r"^(```+|~~~+)")


def _unwrap_fenced_body(body: str) -> str:
    """Reference implementation of the documented "Fenced-body unwrap" step.

    If the body (after leading blank lines) opens with a code fence whose
    matching closing fence is the last non-blank line, strip the outer fence
    and dedent the enclosed lines by their longest common leading whitespace.
    Otherwise return the body unchanged.
    """
    lines = body.splitlines()
    # Find first non-blank line.
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines):
        return body
    open_m = _FENCE_RE.match(lines[start])
    if not open_m:
        return body
    fence = open_m.group(1)
    # Find last non-blank line; it must be a *matching* closing fence: same
    # fence character, length >= the opener, and only fence characters after
    # stripping whitespace.
    end = len(lines) - 1
    while end > start and lines[end].strip() == "":
        end -= 1
    closing = lines[end].strip()
    if end <= start or len(closing) < len(fence) or set(closing) != {fence[0]}:
        return body
    inner = lines[start + 1 : end]
    # Dedent by longest common leading whitespace over non-blank lines.
    indents = [len(ln) - len(ln.lstrip()) for ln in inner if ln.strip()]
    pad = min(indents) if indents else 0
    return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in inner)


# A PR body that is wholly wrapped in one indented code fence — the exact shape
# the "Fenced-body unwrap" step targets. The `## Summary` header lives inside the
# fence and is indented, so the column-0 SUMMARY_RE matches nothing until the
# outer fence is stripped and the lines dedented.
WHOLLY_FENCED_BODY = (
    "```\n"
    "    # Add caching layer to the resolver\n"
    "\n"
    "    ## Summary\n"
    "\n"
    "    - Add an LRU cache to `Resolver::lookup`\n"
    "    - Expose `CacheConfig` with a configurable capacity\n"
    "\n"
    "    ## Out of scope\n"
    "\n"
    "    - Distributed cache backends (separate PR)\n"
    "```"
)


class TestFencedUnwrapExposesSummary:
    def test_fenced_body_hides_header_before_unwrap(self):
        # Before unwrap: the body opens with a fence and SUMMARY_RE finds nothing
        # (the header is indented inside the fence).
        assert WHOLLY_FENCED_BODY.lstrip().startswith("```")
        assert SUMMARY_RE.search(WHOLLY_FENCED_BODY) is None

    def test_unwrap_exposes_summary_header(self):
        unwrapped = _unwrap_fenced_body(WHOLLY_FENCED_BODY)
        assert not unwrapped.lstrip().startswith("```")
        # After strip + dedent the header is at column 0 and SUMMARY_RE matches.
        assert SUMMARY_RE.search(unwrapped) is not None

    def test_unwrap_is_noop_for_unfenced_body(self):
        # An ordinary (non-wholly-fenced) body is returned unchanged.
        plain = "## Summary\n\n- did a thing\n"
        assert _unwrap_fenced_body(plain) == plain

    def test_unwrap_noop_when_closing_fence_shorter_than_opener(self):
        # Opener is ```` (4 backticks); the trailing ``` (3) is NOT a matching
        # close — the closing fence must be at least as long as the opener.
        body = "````\n## Summary\n\n- a thing\n```"
        assert _unwrap_fenced_body(body) == body

    def test_unwrap_noop_when_last_line_has_trailing_text(self):
        # The last line is ```python (fence chars + trailing text) — an info
        # string is an *opening* fence, never a close, so the body is unchanged.
        body = "```\n## Summary\n\n- a thing\n```python"
        assert _unwrap_fenced_body(body) == body

    def test_unwrap_succeeds_for_equal_length_fences(self):
        # Control: equal-length ``` fences (opener == closer) still unwrap.
        body = "```\n## Summary\n\n- a thing\n```"
        out = _unwrap_fenced_body(body)
        assert not out.lstrip().startswith("```")
        assert SUMMARY_RE.search(out) is not None

    def test_fenced_fixture_present_and_self_describing(self):
        # The committed fixture demonstrates the same wholly-fenced shape and
        # carries the standard `<!-- expected -->` annotation (enforced in full
        # by tests/test_pr_promises_fixtures.py).
        text = (FIXTURES / "synthetic-fenced.md").read_text(encoding="utf-8")
        assert "## Summary" in text
        assert "<!-- expected:" in text
