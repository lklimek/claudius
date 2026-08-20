"""Guard: every documented float recipe derives the band it claims.

Producer skills document concrete `likelihood`/`impact` numbers next to a band
name ("emit ONE INFO finding", "derives severity = 1"). Nothing enforced that
the numbers actually derive the named band, so a change to the derivation
formula could silently reband every clean-pass finding — which is exactly what
dropping `relevance` from the mean did to the recipes that had leaned on a low
third term to sink themselves into INFO.

These tests read the numbers out of the skill and run them through the real
`derive_severity_int`, so they pin the property rather than the prose.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from severity_util import derive_finding_severity  # noqa: E402

_NUM = r"(\d*\.\d+|\d+)"
# Both documented spellings: an explicit pair, or one value shared by both axes.
_PAIR_RE = re.compile(rf"`likelihood\s*[≈=]\s*{_NUM},\s*impact\s*[≈=]\s*{_NUM}")
_SHARED_RE = re.compile(rf"`likelihood\s*=\s*impact\s*[≈=]\s*{_NUM}")
# Pre-migration spellings, matched only to skip rather than fail.
_LEGACY_RE = re.compile(r"`risk\s*[≈=][\s\d.]|`risk\s*=\s*impact\s*[≈=]")

# (skill path, anchor text, band the skill claims for that recipe)
RECIPES = [
    ("skills/review-pr/SKILL.md", "PR self-description verified", 1),
    ("skills/review-pr/SKILL.md", "PR body unparseable", 2),
    ("skills/check-pr-comments/SKILL.md", "**Resolved** comments", 1),
    # The doctrine's own worked examples. Left uncovered, the one document that
    # defines the derivation could contradict it — the failure the producer
    # recipes above are guarded against, at the source.
    ("skills/severity/SKILL.md", "**Informational floor.**", 1),
    ("skills/severity/SKILL.md", "scary error dialog on the happy path", 4),
]
IDS = [f"{Path(p).parent.name}:{anchor}" for p, anchor, _ in RECIPES]


def extract_floats(line: str) -> dict[str, float] | None:
    """Parse a documented likelihood/impact recipe out of one line, else None."""
    pair = _PAIR_RE.search(line)
    if pair:
        return {"likelihood": float(pair.group(1)), "impact": float(pair.group(2))}
    shared = _SHARED_RE.search(line)
    if shared:
        value = float(shared.group(1))
        return {"likelihood": value, "impact": value}
    return None


def documented_floats(skill_path: str, anchor: str) -> dict[str, float]:
    """Return the likelihood/impact recipe documented alongside *anchor*.

    Skips while the skill still carries the schema-v3 spelling; fails when it
    carries neither, so a rewrite into an unrecognizable shape cannot pass as
    "migrated" by staying silently skipped.
    """
    path = ROOT / skill_path
    for line in path.read_text(encoding="utf-8").splitlines():
        if anchor not in line:
            continue
        floats = extract_floats(line)
        if floats:
            return floats
        if _LEGACY_RE.search(line):
            pytest.skip(
                f"{skill_path} still documents schema-v3 floats for {anchor!r}; "
                "this test activates when the skill adopts likelihood/impact"
            )
    raise AssertionError(f"No likelihood/impact recipe documented for {anchor!r}")


@pytest.mark.parametrize(
    "line,expected",
    [
        ("`likelihood=0.0, impact=0.0`", {"likelihood": 0.0, "impact": 0.0}),
        ("`likelihood≈0.2, impact≈0.2`", {"likelihood": 0.2, "impact": 0.2}),
        ("x `likelihood = 0.5, impact = 0.7` y", {"likelihood": 0.5, "impact": 0.7}),
        ("`likelihood = impact = 0.0`", {"likelihood": 0.0, "impact": 0.0}),
        ("`risk≈0.2, impact≈0.2, scope=0.0`", None),
        ("no floats here", None),
    ],
)
def test_extractor_handles_the_documented_spellings(line, expected):
    """The guard must not go quietly vacuous if a skill rewords its recipe."""
    assert extract_floats(line) == expected


@pytest.mark.parametrize("skill,anchor,band", RECIPES, ids=IDS)
def test_documented_floats_derive_the_documented_band(skill, anchor, band):
    assert derive_finding_severity(documented_floats(skill, anchor)) == band


@pytest.mark.parametrize("relevance", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("skill,anchor,band", RECIPES, ids=IDS)
def test_relevance_cannot_move_the_documented_band(skill, anchor, band, relevance):
    """Relevance is out of the mean, so no value of it rebands a recipe — the
    reason the old "Pass C scope exception" is no longer load-bearing."""
    floats = documented_floats(skill, anchor)
    assert derive_finding_severity({**floats, "relevance": relevance}) == band


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
