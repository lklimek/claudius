"""Tests for the shared severity_util helpers (band mapping + stats builder)."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import severity_util as su


# ---------------------------------------------------------------------------
# derive_finding_severity — band boundaries (mirrors test_severity_derivation)
# ---------------------------------------------------------------------------
class TestDeriveFindingSeverity:
    @pytest.mark.parametrize(
        "overall,expected",
        [
            (1.0, 5),
            (0.95, 5),
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
    def test_band_boundaries(self, overall, expected):
        # Drive a uniform finding whose mean equals `overall`.
        f = {"risk": overall, "impact": overall, "scope": overall}
        assert su.derive_finding_severity(f) == expected

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
        [(1.0, 5), (0.7, 4), (0.4, 3), (0.1, 2), (0.0, 1)],
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

    def test_explicit_severity_preferred(self):
        sections = [
            {
                "category": "security",
                "findings": [{"severity": 5, "risk": 0.0, "impact": 0.0, "scope": 0.0}],
            }
        ]
        stats = su.build_severity_stats(sections)
        # Explicit integer 5 (CRITICAL) wins over the floats' INFO band.
        assert stats["severity_counts"]["CRITICAL"] == 1
        assert stats["severity_counts"]["INFO"] == 0

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
