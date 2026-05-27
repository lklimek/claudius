"""Tests for OWASP-style severity derivation helpers."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr


# ---------------------------------------------------------------------------
# _derive_overall
# ---------------------------------------------------------------------------
class TestDeriveOverall:
    def test_all_dims_present(self):
        f = {"risk": 0.6, "impact": 0.9, "scope": 0.3}
        assert cr._derive_overall(f) == pytest.approx((0.6 + 0.9 + 0.3) / 3.0)

    def test_zero_values(self):
        f = {"risk": 0.0, "impact": 0.0, "scope": 0.0}
        assert cr._derive_overall(f) == 0.0

    def test_max_values(self):
        f = {"risk": 1.0, "impact": 1.0, "scope": 1.0}
        assert cr._derive_overall(f) == 1.0

    @pytest.mark.parametrize("missing", ["risk", "impact", "scope"])
    def test_any_missing_returns_none(self, missing):
        f = {"risk": 0.5, "impact": 0.5, "scope": 0.5}
        del f[missing]
        assert cr._derive_overall(f) is None

    def test_non_numeric_returns_none(self):
        f = {"risk": "high", "impact": 0.5, "scope": 0.5}
        assert cr._derive_overall(f) is None


# ---------------------------------------------------------------------------
# _derive_severity_int — band table per plan
# ---------------------------------------------------------------------------
class TestDeriveSeverityInt:
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
        assert cr._derive_severity_int(overall) == expected
