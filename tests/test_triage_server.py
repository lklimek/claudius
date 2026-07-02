"""Tests for triage_server.py report loading and the non-finite JSON guard.

``reject_non_finite_constant`` is wired into every report-loading
``json.loads``/``json.load`` call across the pipeline (consolidate_reports,
validate_report, generate_review_report, and here in triage_server's
``_load_report``) so bare NaN/Infinity/-Infinity constants are rejected at
parse time instead of silently corrupting severity math.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import triage_server as ts


def _report(scope: Any) -> dict:
    return {
        "metadata": {"project": "x", "date": "2026-01-01"},
        "findings": [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 4,
                        "title": "T",
                        "location": "src/db.rs:1",
                        "description": "D",
                        "recommendation": "R",
                        "risk": 0.9,
                        "impact": 0.9,
                        "scope": scope,
                    }
                ],
            }
        ],
    }


class TestLoadReportRejectsNonFinite:
    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_load_report_rejects_non_finite_scope(self, tmp_path, monkeypatch, bad):
        report_path = tmp_path / "report.json"
        report_path.write_text(
            json.dumps(_report(bad))
        )  # json.dumps emits bare NaN/Infinity
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        with pytest.raises(ValueError, match="non-finite"):
            ts._load_report()

    def test_load_report_accepts_finite_report(self, tmp_path, monkeypatch):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(0.5)))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        report = ts._load_report()
        assert report["findings"][0]["findings"][0]["scope"] == 0.5


class TestDoPostHandlesNonFiniteReport:
    """_save_triage (called from do_POST) must surface the guard as a clean
    ValueError, not let it fall through do_POST's narrower except clause."""

    def test_save_triage_raises_on_corrupt_report(self, tmp_path, monkeypatch):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(float("nan"))))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        with pytest.raises(ValueError, match="non-finite"):
            ts._save_triage([], "user")
