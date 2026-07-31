"""Tests for the schema-v3 -> v4 severity-float migration.

v3 findings carried ``risk``/``impact``/``scope``; v4 carries
``likelihood``/``impact``/``relevance``. Only ``risk`` migrates by rename. v3
``scope`` was blast radius — which v4 folds into ``impact`` — so it must never
be carried into ``relevance``, whose value decides ``merge_class``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import severity_util as su  # noqa: E402
import validate_report as vr  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"
LEGACY_FIXTURE = FIXTURES / "v3-legacy-floats.json"


def _v3_finding(**over: object) -> dict:
    f = {
        "id": "CODE-001",
        "risk": 0.8,
        "impact": 0.8,
        "scope": 1.0,
        "title": "A v3 finding",
        "location": "src/example.rs:10",
        "description": "Emitted before the v4 float rename.",
        "recommendation": "Nothing to do — this is a fixture.",
    }
    f.update(over)
    return f


def _sections(findings: list[dict]) -> list[dict]:
    return [{"title": "Code Quality", "category": "code_quality", "findings": findings}]


def _envelope(findings: list[dict]) -> dict:
    return {
        "schema_version": "3.2.0",
        "metadata": {"project": "claudius", "date": "2026-07-31"},
        "executive_summary": {"overall_assessment": "Legacy-float fixture."},
        "summary_statistics": {
            "total_findings": len(findings),
            "severity_counts": {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 0,
                "INFO": 0,
            },
        },
        "findings": _sections(findings),
    }


class TestFieldMigration:
    def test_risk_becomes_likelihood(self):
        f = _v3_finding()
        su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == 0.8
        assert "risk" not in f

    def test_scope_value_is_discarded_not_carried_into_relevance(self):
        """The load-bearing rule: a v3 blast radius of 1.0 must NOT become
        relevance 1.0 — relevance is PR-goal fit and drives merge_class."""
        f = _v3_finding(scope=1.0)
        su.migrate_legacy_floats(_envelope([f]))
        assert "scope" not in f
        assert f["relevance"] == su.DEFAULT_MIGRATED_RELEVANCE
        assert f["relevance"] != 1.0

    def test_relevance_defaults_to_adjacent_not_pre_existing(self):
        """0.5 ('adjacent') classifies non_blocking, so a migrated finding lands
        in front of a human instead of being auto-deferred as follow-up."""
        assert su.DEFAULT_MIGRATED_RELEVANCE == 0.5

    def test_impact_is_never_rewritten(self):
        f = _v3_finding(impact=0.3, scope=1.0)
        su.migrate_legacy_floats(_envelope([f]))
        assert f["impact"] == 0.3

    def test_existing_relevance_survives_migration(self):
        f = _v3_finding(relevance=0.1)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["relevance"] == 0.1
        assert report.relevance_defaulted == []

    def test_v4_name_wins_on_collision(self):
        f = _v3_finding(risk=0.2, likelihood=0.9)
        su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == 0.9
        assert "risk" not in f

    def test_v4_finding_is_untouched(self):
        f = {"id": "CODE-002", "likelihood": 0.4, "impact": 0.4}
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f == {"id": "CODE-002", "likelihood": 0.4, "impact": 0.4}
        assert not report

    def test_derivation_uses_the_migrated_likelihood(self):
        f = _v3_finding(risk=1.0, impact=1.0, scope=0.1)
        su.migrate_legacy_floats(_envelope([f]))
        assert su.derive_finding_severity(f) == 5


class TestMigrationShapes:
    def test_producer_section_array(self):
        f = _v3_finding()
        report = su.migrate_legacy_floats(_sections([f]))
        assert f["likelihood"] == 0.8
        assert report.migrated == ["CODE-001"]

    def test_bare_finding_in_producer_array(self):
        """consolidate_reports rescues findings emitted without a section
        wrapper, so the migration has to reach them too."""
        f = _v3_finding()
        su.migrate_legacy_floats([f])
        assert f["likelihood"] == 0.8

    @pytest.mark.parametrize("data", [None, 42, "text", {}, [], {"findings": "nope"}])
    def test_odd_shapes_are_noops(self, data):
        assert not su.migrate_legacy_floats(data)


class TestMigrationWarnings:
    def test_no_warnings_without_legacy_fields(self):
        report = su.migrate_legacy_floats(_envelope([{"id": "X", "likelihood": 0.1}]))
        assert report.warnings("report.json") == []

    def test_rename_warning_names_the_findings(self):
        report = su.migrate_legacy_floats(_envelope([_v3_finding(relevance=0.5)]))
        lines = report.warnings("report.json")
        assert len(lines) == 1
        assert lines[0].startswith("[deprecated] report.json:")
        assert "CODE-001" in lines[0]

    def test_defaulted_relevance_gets_a_louder_second_warning(self):
        report = su.migrate_legacy_floats(_envelope([_v3_finding()]))
        lines = report.warnings("report.json")
        assert len(lines) == 2
        assert "RE-RATE REQUIRED" in lines[1]
        assert "merge_class" in lines[1]
        assert "CODE-001" in lines[1]

    def test_id_list_is_truncated(self):
        findings = [_v3_finding(id=f"CODE-{i:03d}") for i in range(1, 15)]
        line = su.migrate_legacy_floats(_envelope(findings)).warnings("r.json")[0]
        assert "(+4 more)" in line
        assert "CODE-014" not in line

    def test_unidentified_finding_still_reported(self):
        f = {"risk": 0.5, "impact": 0.5}
        report = su.migrate_legacy_floats(_envelope([f]))
        assert report.migrated == ["<unidentified>"]


class TestLegacyFixtureThroughValidateReport:
    """End-to-end: the committed v3 fixture validates only after migration."""

    def _fixture(self) -> dict:
        return json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_genuinely_v3(self):
        finding = self._fixture()["findings"][0]["findings"][0]
        assert "risk" in finding and "scope" in finding

    def test_cli_accepts_it_with_deprecation_warnings(
        self, tmp_path, monkeypatch, capsys
    ):
        path = tmp_path / "legacy.json"
        path.write_text(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        monkeypatch.setattr(sys, "argv", ["validate_report.py", str(path)])

        code = vr.main()
        captured = capsys.readouterr()

        assert code == 0
        assert "Valid:" in captured.out
        assert "[deprecated]" in captured.err
        assert "RE-RATE REQUIRED" in captured.err

    def test_unmigrated_fixture_fails_the_schema(self, tmp_path, monkeypatch, capsys):
        """Proves the shim is what saves it: bypass the migration and the v3
        float names are rejected outright."""
        path = tmp_path / "legacy.json"
        path.write_text(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        monkeypatch.setattr(sys, "argv", ["validate_report.py", str(path)])
        monkeypatch.setattr(
            vr, "migrate_legacy_floats", lambda data: su.LegacyFloatMigration([], [])
        )

        assert vr.main() == 1
        assert "Validation failed" in capsys.readouterr().err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
