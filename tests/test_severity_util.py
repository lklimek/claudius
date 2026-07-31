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
# derive_finding_severity — band mapping through the likelihood/impact path.
# Exact threshold values must remain in their intended bands even when the
# arithmetic mean lands an IEEE-754 epsilon below the mathematical boundary.
# ---------------------------------------------------------------------------
class TestDeriveFindingSeverity:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0.9, 5),  # CRITICAL boundary
            (0.7, 4),  # HIGH boundary
            (0.4, 3),  # MEDIUM boundary
            (0.1, 2),  # LOW boundary
            (0.05, 1),  # INFO
        ],
    )
    def test_band_mapping(self, value, expected):
        f = {"likelihood": value, "impact": value, "relevance": value}
        assert su.derive_finding_severity(f) == expected

    def test_mixed_dimensions_use_mean(self):
        # mean of 1.0/0.8 = 0.9 -> CRITICAL band.
        assert su.derive_finding_severity({"likelihood": 1.0, "impact": 0.8}) == 5

    @pytest.mark.parametrize("missing", ["likelihood", "impact"])
    def test_any_missing_returns_none(self, missing):
        f = {"likelihood": 0.5, "impact": 0.5, "relevance": 0.5}
        del f[missing]
        assert su.derive_finding_severity(f) is None

    def test_non_numeric_returns_none(self):
        f = {"likelihood": "high", "impact": 0.5, "relevance": 0.5}
        assert su.derive_finding_severity(f) is None

    def test_bool_is_not_numeric(self):
        f = {"likelihood": True, "impact": 0.5, "relevance": 0.5}
        assert su.derive_finding_severity(f) is None

    @pytest.mark.parametrize("axis", ["likelihood", "impact"])
    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_non_finite_dimension_returns_none(self, axis, bad):
        """A NaN dimension must NOT silently sink a CRITICAL finding to INFO, nor
        may +Infinity force it to CRITICAL — non-finite floats yield None."""
        f = {"likelihood": 0.95, "impact": 0.95, "relevance": 0.95}
        f[axis] = bad
        assert su.derive_overall(f) is None
        assert su.derive_finding_severity(f) is None


# ---------------------------------------------------------------------------
# relevance is excluded from the severity math (severity skill § Derivation):
# it rates fit to the PR's goal, not how bad the defect is.
# ---------------------------------------------------------------------------
class TestRelevanceExcludedFromMath:
    @pytest.mark.parametrize("relevance", [0.0, 0.1, 0.5, 1.0, "unrated", None])
    def test_relevance_never_moves_the_band(self, relevance):
        f = {"likelihood": 1.0, "impact": 1.0, "relevance": relevance}
        assert su.derive_overall(f) == 1.0
        assert su.derive_finding_severity(f) == 5

    def test_absent_relevance_still_derives(self):
        assert su.derive_finding_severity({"likelihood": 0.8, "impact": 0.8}) == 4

    def test_preexisting_catastrophe_is_not_laundered_to_medium(self):
        """A CRITICAL defect the PR did not introduce stays CRITICAL. Under the
        old 3-term mean, relevance 0.1 dragged 1.0/1.0 down to 0.7."""
        f = {"likelihood": 1.0, "impact": 1.0, "relevance": 0.1}
        assert su.derive_finding_severity(f) == 5

    def test_non_finite_relevance_does_not_block_derivation(self):
        f = {"likelihood": 0.5, "impact": 0.5, "relevance": float("nan")}
        assert su.derive_overall(f) == 0.5


# ---------------------------------------------------------------------------
# derive_overall / derive_severity_int (the underlying primitives)
# ---------------------------------------------------------------------------
class TestPrimitives:
    def test_derive_overall_mean(self):
        assert su.derive_overall(
            {"likelihood": 0.6, "impact": 0.9, "relevance": 0.3}
        ) == pytest.approx((0.6 + 0.9) / 2.0)

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
                    {"likelihood": 0.8, "impact": 0.8, "relevance": 1.0},  # HIGH
                    {"likelihood": 0.4, "impact": 0.4, "relevance": 0.4},  # MEDIUM
                ],
            }
        ]
        stats = su.build_severity_stats(sections)
        assert stats["total_findings"] == 2
        assert stats["severity_counts"]["HIGH"] == 1
        assert stats["severity_counts"]["MEDIUM"] == 1

    def test_derived_floats_preferred_over_conflicting_explicit_severity(self):
        # The floats are the single source of truth (severity skill doctrine):
        # a derived band wins even over a conflicting explicit integer,
        # matching cmd_assemble's precedence in consolidate_reports.py.
        sections = [
            {
                "category": "security",
                "findings": [
                    {"severity": 5, "likelihood": 0.0, "impact": 0.0, "relevance": 0.0}
                ],
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
                "findings": [
                    {"likelihood": 0.8, "impact": 0.8, "relevance": 1.0}
                ],  # HIGH
            },
            {
                "category": "security",
                "findings": [
                    {"likelihood": 0.95, "impact": 0.95, "relevance": 1.0}
                ],  # CRITICAL
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
                f'{{"relevance": {literal}}}',
                parse_constant=su.reject_non_finite_constant,
            )

    def test_default_json_loads_would_accept_nan(self):
        """Guard rationale: without the callback, json silently decodes NaN."""
        assert math.isnan(json.loads('{"relevance": NaN}')["relevance"])

    def test_finite_json_still_parses(self):
        data = json.loads(
            '{"relevance": 0.5}', parse_constant=su.reject_non_finite_constant
        )
        assert data == {"relevance": 0.5}

    @pytest.mark.parametrize("literal", ["1e400", "-1e400"])
    def test_overflowing_literal_bypasses_the_callback(self, literal):
        """The guard covers bare NaN/Infinity tokens only. `1e400` is an
        ordinary JSON number that Python converts to inf without consulting
        parse_constant, so the docstring must not claim otherwise — the
        downstream isinf check and the schema's maximum are what catch it."""
        value = json.loads(
            f'{{"likelihood": {literal}}}',
            parse_constant=su.reject_non_finite_constant,
        )["likelihood"]
        assert math.isinf(value)
        assert su.derive_overall({"likelihood": value, "impact": 0.5}) is None
