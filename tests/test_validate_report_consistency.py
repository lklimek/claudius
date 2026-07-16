"""Tests for the non-blocking consistency gate in validate_report.py.

The gate emits ``[consistency]`` warnings to stderr without failing an
otherwise-valid report. It covers rating, merge-class, and schema coherence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import validate_report as vr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"


def _section(findings: list[dict], category: str = "code_quality") -> dict:
    return {"title": category.title(), "category": category, "findings": findings}


def _finding(idx: int, **over: object) -> dict:
    """A schema-valid finding with sensible defaults, overridable per axis."""
    f = {
        "id": f"CODE-{idx:03d}",
        "risk": 0.3,
        "impact": 0.3,
        "scope": 0.3,
        "title": f"Finding {idx}",
        "location": f"src/example.rs:{idx}",
        "description": "A finding used to exercise the consistency gate.",
        "recommendation": "Nothing to do — this is a fixture.",
    }
    f.update(over)
    return f


def _report(sections: list[dict]) -> dict:
    return {
        "schema_version": "3.0.0",
        "metadata": {"project": "claudius", "date": "2026-06-10"},
        "executive_summary": {"overall_assessment": "Consistency-gate fixture."},
        "summary_statistics": {
            "total_findings": sum(len(s["findings"]) for s in sections),
            "severity_counts": {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 0,
                "INFO": 0,
            },
        },
        "findings": sections,
    }


# ---------------------------------------------------------------------------
# check_consistency — label/band mismatch (check i)
# ---------------------------------------------------------------------------
class TestLabelBandMismatch:
    def test_explicit_severity_disagrees_with_floats_warns(self):
        # floats mean ≈0.1 -> band 2 (LOW); explicit severity 4 (HIGH) disagrees.
        report = _report(
            [_section([_finding(1, severity=4, risk=0.1, impact=0.1, scope=0.1)])]
        )
        warnings = vr.check_consistency(report)
        assert any("CODE-001" in w and "severity=4" in w for w in warnings)
        assert all(w.startswith("[consistency]") for w in warnings)

    def test_explicit_severity_matching_floats_is_silent(self):
        # mean 0.3 -> band 2 (LOW); explicit severity 2 agrees -> no mismatch warn.
        report = _report(
            [_section([_finding(1, severity=2, risk=0.3, impact=0.3, scope=0.3)])]
        )
        warnings = vr.check_consistency(report)
        assert not any("disagrees with band" in w for w in warnings)

    def test_overall_severity_disagrees_with_explicit_severity_warns(self):
        report = _report(
            [
                _section(
                    [
                        _finding(
                            1,
                            severity=5,
                            risk=0.3,
                            impact=0.3,
                            scope=0.3,
                            overall_severity=0.3,  # band 2, not 5
                        )
                    ]
                )
            ]
        )
        warnings = vr.check_consistency(report)
        assert any("overall_severity" in w for w in warnings)

    def test_floatless_explicit_severity_never_warns(self):
        # No risk/impact/scope -> nothing to compare against.
        report = _report([_section([{"id": "CODE-001", "severity": 4}])])
        assert vr.check_consistency(report) == []


class TestMergeClassAdvisories:
    def test_merge_class_requires_schema_3_2_0(self):
        report = _report([_section([_finding(1, merge_class="non_blocking")])])
        report["schema_version"] = "3.1.0"

        warnings = vr.check_consistency(report)
        assert any("require schema_version=3.2.0" in warning for warning in warnings)

        report["schema_version"] = "3.2.0"
        warnings = vr.check_consistency(report)
        assert not any(
            "require schema_version=3.2.0" in warning for warning in warnings
        )

    def test_report_level_merge_fields_require_schema_3_2_0(self):
        # merge_class in top_findings and merge_class_counts in
        # summary_statistics are 3.2.0-only additions that live outside the
        # per-section findings the finding loop scans.
        report = _report([_section([_finding(1)])])
        report["schema_version"] = "3.1.0"
        report["top_findings"] = [
            {
                "id": "CODE-001",
                "severity": 4,
                "title": "Finding 1",
                "location": "src/example.rs:1",
                "merge_class": "blocking",
            }
        ]
        report["summary_statistics"]["merge_class_counts"] = {"blocking": 1}

        warnings = vr.check_consistency(report)
        assert any("top_findings[].merge_class" in w for w in warnings)
        assert any("summary_statistics.merge_class_counts" in w for w in warnings)

        report["schema_version"] = "3.2.0"
        assert not any(
            "report: 3.2.0-only fields" in w for w in vr.check_consistency(report)
        )

    def test_false_positive_with_non_disputed_merge_class_warns(self):
        report = _report(
            [
                _section(
                    [
                        _finding(
                            1,
                            ai_verdict="false_positive",
                            merge_class="blocking",
                            intent_basis="A claimed requirement.",
                        )
                    ]
                )
            ]
        )
        warnings = vr.check_consistency(report)
        assert any(
            "false_positive" in warning and "disputed" in warning
            for warning in warnings
        )

    def test_duplicate_with_disputed_merge_class_is_silent(self):
        report = _report(
            [_section([_finding(1, ai_verdict="duplicate", merge_class="disputed")])]
        )
        warnings = vr.check_consistency(report)
        assert not any(
            "duplicate" in warning and "merge_class" in warning for warning in warnings
        )

    def test_blocking_without_nonempty_intent_basis_warns(self):
        for intent_basis in (None, "", "   "):
            report = _report(
                [
                    _section(
                        [
                            _finding(
                                1,
                                merge_class="blocking",
                                intent_basis=intent_basis,
                            )
                        ]
                    )
                ]
            )
            warnings = vr.check_consistency(report)
            assert any("intent_basis" in warning for warning in warnings)


# ---------------------------------------------------------------------------
# check_consistency — un-rated-axis smell (check ii)
# ---------------------------------------------------------------------------
class TestUnratedAxis:
    def test_scope_pinned_at_one_warns_for_scope(self):
        # 5 findings, every scope=1.0 but risk/impact vary -> only scope flags.
        findings = [
            _finding(
                i, risk=round(0.2 + 0.05 * i, 2), impact=round(0.1 * i, 2), scope=1.0
            )
            for i in range(1, 6)
        ]
        warnings = vr.check_consistency(_report([_section(findings)]))
        scope_warns = [w for w in warnings if "scope=1.0" in w]
        assert len(scope_warns) == 1
        assert "5/5 findings have scope=1.0" in scope_warns[0]
        assert "blast radius" in scope_warns[0]
        # risk/impact vary, so they must NOT be flagged.
        assert not any("risk=" in w or "impact=" in w for w in warnings)

    def test_eighty_percent_share_triggers(self):
        # 4 of 5 share scope=1.0 (80%) -> fires at the threshold boundary.
        # risk/impact are varied so only scope's share is under test.
        findings = [
            _finding(i, scope=1.0, risk=round(0.1 * i, 2), impact=round(0.12 * i, 2))
            for i in range(1, 5)
        ]
        findings.append(_finding(5, scope=0.2, risk=0.6, impact=0.7))
        warnings = vr.check_consistency(_report([_section(findings)]))
        assert any("4/5 findings have scope=1.0" in w for w in warnings)

    def test_below_threshold_is_silent(self):
        # 3 of 5 share scope=1.0 (60%) -> below 80%; risk/impact varied so no
        # other axis fires either.
        findings = [
            _finding(i, scope=1.0, risk=round(0.1 * i, 2), impact=round(0.12 * i, 2))
            for i in range(1, 4)
        ]
        findings += [
            _finding(4, scope=0.5, risk=0.4, impact=0.4),
            _finding(5, scope=0.2, risk=0.6, impact=0.9),
        ]
        warnings = vr.check_consistency(_report([_section(findings)]))
        assert not any("may be unrated" in w for w in warnings)

    def test_tiny_report_never_flags_axis(self):
        # Under the 5-finding floor, uniformity is expected, not a smell.
        findings = [_finding(i, scope=1.0) for i in range(1, 5)]
        warnings = vr.check_consistency(_report([_section(findings)]))
        assert not any("may be unrated" in w for w in warnings)


# ---------------------------------------------------------------------------
# Clean report — neither warning, and CLI still exits 0
# ---------------------------------------------------------------------------
class TestCleanReport:
    def test_properly_rated_report_no_warnings(self):
        # 5 findings, every axis genuinely varied, severities omitted (derived).
        findings = [
            _finding(
                i,
                risk=round(0.1 * i, 2),
                impact=round(0.15 * i, 2),
                scope=round(0.1 + 0.12 * i, 2),
            )
            for i in range(1, 6)
        ]
        assert vr.check_consistency(_report([_section(findings)])) == []

    def test_full_fixture_no_warnings(self):
        report = json.loads((FIXTURES / "v3-full.json").read_text())
        assert vr.check_consistency(report) == []


# ---------------------------------------------------------------------------
# CLI integration — warnings go to stderr; exit code stays 0 when valid.
# ---------------------------------------------------------------------------
def _run_cli(report: object, tmp_path: Path, monkeypatch, capsys, *extra_args: str):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(sys, "argv", ["validate_report.py", str(path), *extra_args])
    code = vr.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestCliExitCodes:
    def test_unrated_axis_warns_but_exits_zero(self, tmp_path, monkeypatch, capsys):
        findings = [
            _finding(i, risk=round(0.1 * i, 2), impact=round(0.12 * i, 2), scope=1.0)
            for i in range(1, 6)
        ]
        code, out, err = _run_cli(
            _report([_section(findings)]), tmp_path, monkeypatch, capsys
        )
        assert code == 0
        assert "Valid:" in out
        assert "[consistency]" in err
        assert "scope=1.0" in err

    def test_mismatch_warns_but_exits_zero(self, tmp_path, monkeypatch, capsys):
        report = _report(
            [_section([_finding(1, severity=5, risk=0.1, impact=0.1, scope=0.1)])]
        )
        code, _out, err = _run_cli(report, tmp_path, monkeypatch, capsys)
        assert code == 0
        assert "[consistency]" in err
        assert "severity=5" in err

    def test_clean_report_exits_zero_with_no_consistency_warning(
        self, tmp_path, monkeypatch, capsys
    ):
        findings = [
            _finding(
                i,
                risk=round(0.1 * i, 2),
                impact=round(0.15 * i, 2),
                scope=round(0.1 + 0.12 * i, 2),
            )
            for i in range(1, 6)
        ]
        code, out, err = _run_cli(
            _report([_section(findings)]), tmp_path, monkeypatch, capsys
        )
        assert code == 0
        assert "Valid:" in out
        assert "[consistency]" not in err

    def test_schema_invalid_report_still_fails(self, tmp_path, monkeypatch, capsys):
        # A missing required float keeps the schema failure path (exit 1).
        bad = _report([_section([{"id": "CODE-001", "title": "x"}])])
        code, _out, err = _run_cli(bad, tmp_path, monkeypatch, capsys)
        assert code == 1
        assert "Validation failed" in err

    def test_producer_mode_accepts_finding_section_array(
        self, tmp_path, monkeypatch, capsys
    ):
        producer_report = [_section([_finding(1)])]

        code, out, err = _run_cli(
            producer_report, tmp_path, monkeypatch, capsys, "--producer"
        )

        assert code == 0
        assert "Valid:" in out
        assert err == ""

    def test_default_mode_rejects_finding_section_array(
        self, tmp_path, monkeypatch, capsys
    ):
        producer_report = [_section([_finding(1)])]

        code, _out, err = _run_cli(producer_report, tmp_path, monkeypatch, capsys)

        assert code == 1
        assert "not of type 'object'" in err

    def test_producer_mode_rejects_bare_finding_array(
        self, tmp_path, monkeypatch, capsys
    ):
        code, _out, err = _run_cli(
            [_finding(1)], tmp_path, monkeypatch, capsys, "--producer"
        )

        assert code == 1
        assert "'findings' is a required property" in err

    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_non_finite_float_rejected_at_parse(
        self, tmp_path, monkeypatch, capsys, bad
    ):
        """A bare NaN/Infinity must be a parse error (exit 2), never reported
        'Valid' — jsonschema's numeric range check silently passes NaN."""
        report = _report([_section([_finding(1, scope=bad)])])
        code, out, err = _run_cli(report, tmp_path, monkeypatch, capsys)
        assert code == 2
        assert "Valid:" not in out
        assert "Invalid JSON" in err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
