"""Tests for the shared severity_util helpers (band mapping + stats builder)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import severity_util as su


# ---------------------------------------------------------------------------
# derive_finding_severity — band mapping. Boundary exactness is covered by
# TestPrimitives below against derive_severity_int directly (driving through the
# float mean would re-introduce IEEE-754 rounding at the band edges, e.g.
# (0.7+0.7+0.7)/3 = 0.6999…). Here we just confirm the float trio maps to the
# expected band well inside each range.
# ---------------------------------------------------------------------------
class TestDeriveFindingSeverity:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0.95, 5),  # CRITICAL
            (0.8, 4),  # HIGH
            (0.5, 3),  # MEDIUM
            (0.2, 2),  # LOW
            (0.05, 1),  # INFO
        ],
    )
    def test_band_mapping(self, value, expected):
        f = {"risk": value, "impact": value, "scope": value}
        assert su.derive_finding_severity(f) == expected

    def test_mixed_dimensions_use_mean(self):
        # mean of 1.0/0.7/1.0 = 0.9 -> CRITICAL band.
        assert (
            su.derive_finding_severity({"risk": 1.0, "impact": 0.7, "scope": 1.0}) == 5
        )

    @pytest.mark.parametrize("missing", ["risk", "impact", "scope"])
    def test_any_missing_returns_none(self, missing):
        f = {"risk": 0.5, "impact": 0.5, "scope": 0.5}
        del f[missing]
        assert su.derive_finding_severity(f) is None

    def test_non_numeric_returns_none(self):
        f = {"risk": "high", "impact": 0.5, "scope": 0.5}
        assert su.derive_finding_severity(f) is None

    def test_bool_is_not_numeric(self):
        f = {"risk": True, "impact": 0.5, "scope": 0.5}
        assert su.derive_finding_severity(f) is None

    @pytest.mark.parametrize("axis", ["risk", "impact", "scope"])
    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_non_finite_dimension_returns_none(self, axis, bad):
        """A NaN scope must NOT silently sink a CRITICAL finding to INFO, nor may
        +Infinity force it to CRITICAL — non-finite floats yield None (can't derive)."""
        f = {"risk": 0.95, "impact": 0.95, "scope": 0.95}
        f[axis] = bad
        assert su.derive_overall(f) is None
        assert su.derive_finding_severity(f) is None


# ---------------------------------------------------------------------------
# derive_overall / derive_severity_int (the underlying primitives)
# ---------------------------------------------------------------------------
class TestPrimitives:
    def test_derive_overall_mean(self):
        assert su.derive_overall(
            {"risk": 0.6, "impact": 0.9, "scope": 0.3}
        ) == pytest.approx((0.6 + 0.9 + 0.3) / 3.0)

    @pytest.mark.parametrize(
        "overall,expected",
        [
            (1.0, 5),
            (0.9, 5),
            (0.89, 4),
            (0.7, 4),
            (0.69, 3),
            (0.4, 3),
            (0.39, 2),
            (0.1, 2),
            (0.09, 1),
            (0.0, 1),
        ],
    )
    def test_derive_severity_int_bands(self, overall, expected):
        assert su.derive_severity_int(overall) == expected


# ---------------------------------------------------------------------------
# build_severity_stats — counts + category matrix
# ---------------------------------------------------------------------------
class TestBuildSeverityStats:
    def test_counts_from_floats_only(self):
        sections = [
            {
                "category": "pr_comments",
                "findings": [
                    {"risk": 0.8, "impact": 0.8, "scope": 1.0},  # HIGH
                    {"risk": 0.4, "impact": 0.4, "scope": 0.4},  # MEDIUM
                ],
            }
        ]
        stats = su.build_severity_stats(sections)
        assert stats["total_findings"] == 2
        assert stats["severity_counts"]["HIGH"] == 1
        assert stats["severity_counts"]["MEDIUM"] == 1

    def test_derived_floats_preferred_over_conflicting_explicit_severity(self):
        # The float trio is the single source of truth (severity skill
        # doctrine): a derived band wins even over a conflicting explicit
        # integer, matching cmd_assemble's precedence in consolidate_reports.py.
        sections = [
            {
                "category": "security",
                "findings": [{"severity": 5, "risk": 0.0, "impact": 0.0, "scope": 0.0}],
            }
        ]
        stats = su.build_severity_stats(sections)
        assert stats["severity_counts"]["INFO"] == 1
        assert stats["severity_counts"]["CRITICAL"] == 0

    def test_explicit_severity_used_when_floats_absent(self):
        sections = [
            {
                "category": "security",
                "findings": [{"severity": 5}],
            }
        ]
        stats = su.build_severity_stats(sections)
        assert stats["severity_counts"]["CRITICAL"] == 1

    def test_floatless_finding_falls_back_to_info(self):
        sections = [{"category": "code_quality", "findings": [{"title": "x"}]}]
        stats = su.build_severity_stats(sections)
        assert stats["severity_counts"]["INFO"] == 1

    def test_category_matrix_shape_and_totals(self):
        sections = [
            {
                "category": "pr_comments",
                "findings": [{"risk": 0.8, "impact": 0.8, "scope": 1.0}],  # HIGH
            },
            {
                "category": "security",
                "findings": [{"risk": 0.95, "impact": 0.95, "scope": 1.0}],  # CRITICAL
            },
        ]
        stats = su.build_severity_stats(sections)
        matrix = stats["severity_category_matrix"]
        # One row per band, in SEV_ORDER.
        assert [r["severity"] for r in matrix] == su.SEV_ORDER
        high = next(r for r in matrix if r["severity"] == "HIGH")
        crit = next(r for r in matrix if r["severity"] == "CRITICAL")
        assert high["pr_comments"] == 1
        assert high["total"] == 1
        assert crit["security"] == 1
        assert crit["total"] == 1
        # Every row carries every tracked category as a key.
        for row in matrix:
            for cat in su.MATRIX_CATEGORIES:
                assert cat in row

    def test_empty_sections(self):
        stats = su.build_severity_stats([])
        assert stats["total_findings"] == 0
        assert all(v == 0 for v in stats["severity_counts"].values())


# ---------------------------------------------------------------------------
# reject_non_finite_constant — json parse_constant callback
# ---------------------------------------------------------------------------
class TestRejectNonFiniteConstant:
    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_json_loads_rejects_bare_constant(self, literal):
        """Wired as parse_constant, bare non-finite literals raise ValueError."""
        with pytest.raises(ValueError):
            json.loads(
                f'{{"scope": {literal}}}',
                parse_constant=su.reject_non_finite_constant,
            )

    def test_default_json_loads_would_accept_nan(self):
        """Guard rationale: without the callback, json silently decodes NaN."""
        assert math.isnan(json.loads('{"scope": NaN}')["scope"])

    def test_finite_json_still_parses(self):
        data = json.loads(
            '{"scope": 0.5}', parse_constant=su.reject_non_finite_constant
        )
        assert data == {"scope": 0.5}
