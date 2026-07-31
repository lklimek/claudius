"""Tests for the schema-v3 -> v4 severity-float migration.

v3 findings carried ``risk``/``impact``/``scope``; v4 carries
``likelihood``/``impact``/``relevance``. Only ``risk`` migrates by rename. v3
``scope`` was blast radius — which v4 folds into ``impact`` — so it must never
be carried into ``relevance``, whose value decides ``merge_class``.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import generate_review_report as grr  # noqa: E402
import severity_util as su  # noqa: E402
import validate_report as vr  # noqa: E402

LEGACY_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "legacy" / "v3-legacy-floats.json"
)

# Distinguishes "key omitted" from "key present and None" in parametrized cases.
_ABSENT = object()


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

    def test_existing_relevance_survives_when_no_scope_collides(self):
        f = _v3_finding(relevance=0.1)
        del f["scope"]
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["relevance"] == 0.1
        assert report.relevance_defaulted == []


class TestCollisionsResolveBySemantics:
    """The two pairs collide for different reasons and resolve by different
    rules. `risk`/`likelihood` are one quantity, so the higher wins — v4-wins
    would turn `risk 1.0, likelihood 0.1` into MEDIUM from a CRITICAL, and this
    pair feeds the severity mean. `scope`/`relevance` are different quantities,
    so the producer's `relevance` wins and `scope` is discarded: taking the
    higher would import a blast radius into the field deciding `merge_class`.
    """

    def test_likelihood_collision_takes_the_higher(self):
        f = _v3_finding(risk=1.0, likelihood=0.1, impact=1.0)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == 1.0
        assert "risk" not in f
        assert su.derive_finding_severity(f) == 5
        assert report.collisions == ["CODE-001"]

    def test_relevance_collision_keeps_the_producers_rating(self):
        """A producer that supplied `relevance` has actually rated PR-fit, so
        its value is authoritative however low. `max` here would put a blast
        radius of 1.0 into the field that decides merge_class."""
        f = _v3_finding(scope=1.0, relevance=0.1)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["relevance"] == 0.1
        assert "scope" not in f
        assert report.collisions == ["CODE-001"]

    def test_keeping_the_lower_relevance_cannot_sink_a_band(self):
        """Why `max` is not needed here: relevance is not in the severity mean,
        so the producer's lower value cannot under-report severity."""
        f = _v3_finding(risk=1.0, impact=1.0, scope=1.0, relevance=0.1)
        su.migrate_legacy_floats(_envelope([f]))
        assert f["relevance"] == 0.1
        assert f["severity"] == 5

    def test_scope_alone_is_still_discarded_not_carried(self):
        f = _v3_finding(scope=1.0)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["relevance"] == su.DEFAULT_MIGRATED_RELEVANCE
        assert report.collisions == []

    @pytest.mark.parametrize("scope", [0.0, 0.1, 0.5, 1.0, None, "wide"])
    @pytest.mark.parametrize("relevance", [_ABSENT, 0.0, 0.1, 0.5, 1.0])
    def test_scope_never_contributes_a_value_to_relevance(self, scope, relevance):
        """The invariant over every combination rather than one example: no
        input makes a v3 blast radius become PR-fit. A supplied `relevance` is
        kept exactly; an absent one defaults. This is the defect that started
        the thread, so it is pinned exhaustively rather than by sample."""
        over: dict = {"scope": scope}
        if relevance is not _ABSENT:
            over["relevance"] = relevance
        f = _v3_finding(**over)

        su.migrate_legacy_floats(_envelope([f]))

        expected = su.DEFAULT_MIGRATED_RELEVANCE if relevance is _ABSENT else relevance
        assert f["relevance"] == expected
        assert "scope" not in f

    def test_agreeing_values_are_not_a_collision(self):
        f = _v3_finding(risk=0.8, likelihood=0.8)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == 0.8
        assert report.collisions == []

    def test_non_numeric_pair_keeps_the_v4_value(self):
        f = _v3_finding(risk=1.0, likelihood="high")
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == "high"
        assert report.collisions == []

    def test_collision_is_reported_in_its_own_warning(self):
        f = _v3_finding(risk=1.0, likelihood=0.1)
        lines = su.migrate_legacy_floats(_envelope([f])).warnings("report.json")
        collision_lines = [ln for ln in lines if "HIGHER" in ln]
        assert len(collision_lines) == 1
        assert "CODE-001" in collision_lines[0]

    def test_v4_finding_is_untouched(self):
        f = {"id": "CODE-002", "likelihood": 0.4, "impact": 0.4}
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f == {"id": "CODE-002", "likelihood": 0.4, "impact": 0.4}
        assert not report

    def test_derivation_uses_the_migrated_likelihood(self):
        f = _v3_finding(risk=1.0, impact=1.0, scope=0.1)
        su.migrate_legacy_floats(_envelope([f]))
        assert su.derive_finding_severity(f) == 5


class TestV3InformationalFindingsTakeTheFloor:
    """The pre-v4 informational convention was `risk = impact = 0.1, scope = 0.0`
    for praise, verified-clean passes and RESOLVED comments. It derived to 0.067
    (INFO) under the three-term mean and derives to 0.1 (LOW) under the two-term
    one, so a straight rename refiles every settled comment in an in-flight
    report as open LOW work.
    """

    def _informational(self, **over: object) -> dict:
        return _v3_finding(**{"risk": 0.1, "impact": 0.1, "scope": 0.0, **over})

    def test_v3_informational_lands_on_the_floor(self):
        f = self._informational()
        report = su.migrate_legacy_floats(_envelope([f]))
        assert f["likelihood"] == 0.0
        assert f["impact"] == 0.0
        assert f["relevance"] == 0.0
        assert f["severity"] == 1
        assert report.floored == ["CODE-001"]

    def test_without_the_floor_it_would_have_become_low(self):
        """Pins the defect: renaming alone gives 0.1 -> LOW."""
        assert su.derive_finding_severity({"likelihood": 0.1, "impact": 0.1}) == 2

    def test_floored_finding_is_not_counted_as_relevance_defaulted(self):
        report = su.migrate_legacy_floats(_envelope([self._informational()]))
        assert report.relevance_defaulted == []

    def test_floor_is_reported_in_its_own_warning(self):
        lines = su.migrate_legacy_floats(_envelope([self._informational()])).warnings(
            "r.json"
        )
        floor_lines = [ln for ln in lines if "Informational floor" in ln]
        assert len(floor_lines) == 1
        assert "CODE-001" in floor_lines[0]

    @pytest.mark.parametrize(
        "over",
        [
            {"scope": 0.2},  # a real, if narrow, blast radius
            {"risk": 0.2},  # above the informational ceiling
            {"impact": 0.4},
            {"likelihood": 0.1},  # half-migrated: ambiguous, use the normal path
            {"relevance": 0.1},
            {"risk": "low"},
        ],
    )
    def test_non_informational_trios_are_untouched_by_the_heuristic(self, over):
        f = self._informational(**over)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert report.floored == []

    def test_heuristic_cannot_demote_anything_above_info(self):
        """Safety argument, executed: every trio the heuristic matches already
        derived to INFO under the v3 three-term mean, so flooring it cannot
        lower a band that was ever above INFO."""
        for risk in (0.0, 0.05, 0.1):
            for impact in (0.0, 0.05, 0.1):
                assert su.derive_severity_int((risk + impact + 0.0) / 3.0) == 1


class TestUnusableFloatsFailHigh:
    """`derive_overall` returning None used to resolve to INFO — the one band
    meaning "no action required" — in a tool whose damaging failure is
    under-reporting.
    """

    def test_surviving_dimension_sets_the_band(self):
        assert su._effective_severity({"likelihood": 1.0}) == 5
        assert su._effective_severity({"impact": 1.0}) == 5

    def test_highest_of_dimension_and_explicit_severity_wins(self):
        assert su._effective_severity({"likelihood": 1.0, "severity": 2}) == 5
        assert su._effective_severity({"likelihood": 0.0, "severity": 4}) == 4

    def test_no_usable_signal_still_falls_to_info(self):
        assert su._effective_severity({"title": "x"}) == 1

    def test_non_finite_dimension_is_not_usable(self):
        assert su._effective_severity({"likelihood": float("inf")}) == 1

    def test_scope_only_v3_finding_is_reported_not_silently_info(self):
        """The shim triggers on `risk` OR `scope`; a scope-only finding leaves
        migration with no likelihood, which must be announced."""
        f = _v3_finding(impact=1.0)
        del f["risk"]
        report = su.migrate_legacy_floats(_envelope([f]))
        assert report.likelihood_missing == ["CODE-001"]
        assert su._effective_severity(f) == 5
        assert any("no usable 'likelihood'" in ln for ln in report.warnings("r.json"))


class TestStaleLabelsAreRecomputed:
    """A v3 report carries `severity`/`overall_severity` computed under the
    three-term mean. Renaming the floats and leaving those alone reports the
    old, lower band — renderers short-circuit when both are present, and
    cmd_regenerate rebuilds top_findings and the summary matrix from the stale
    integer. That is the laundering this whole change exists to kill.
    """

    def test_stale_band_is_recomputed_from_the_v4_floats(self):
        # v3: (1.0 + 1.0 + 0.2) / 3 = 0.733 -> HIGH. v4: (1.0 + 1.0) / 2 -> CRITICAL.
        f = _v3_finding(
            risk=1.0, impact=1.0, scope=0.2, severity=4, overall_severity=0.7333
        )
        su.migrate_legacy_floats(_envelope([f]))
        assert f["severity"] == 5
        assert f["overall_severity"] == 1.0

    def test_stale_label_dropped_when_floats_cannot_derive(self):
        f = _v3_finding(risk="high", severity=4, overall_severity=0.73)
        su.migrate_legacy_floats(_envelope([f]))
        assert "severity" not in f
        assert "overall_severity" not in f

    def test_untouched_v4_finding_keeps_its_label(self):
        f = {"id": "CODE-002", "likelihood": 0.1, "impact": 0.1, "severity": 4}
        su.migrate_legacy_floats(_envelope([f]))
        assert f["severity"] == 4


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
        f = _v3_finding(relevance=0.5)
        del f["scope"]
        lines = su.migrate_legacy_floats(_envelope([f])).warnings("report.json")
        assert lines[0].startswith("[deprecated] report.json:")
        assert "CODE-001" in lines[0]

    def test_rerate_warning_is_unconditional_and_names_impact(self):
        """Every migrated finding needs re-rating: v3 rated `impact` without
        blast radius, so the value carried over under-rates wide findings."""
        f = _v3_finding(relevance=0.5)
        del f["scope"]
        lines = su.migrate_legacy_floats(_envelope([f])).warnings("report.json")
        rerate = [ln for ln in lines if "RE-RATE REQUIRED" in ln]
        assert len(rerate) == 1
        assert "impact" in rerate[0]
        assert "under-rated" in rerate[0]
        assert "CODE-001" in rerate[0]
        # relevance was supplied, so the defaulting clause must stay silent.
        assert "defaulted" not in rerate[0]

    def test_defaulted_relevance_is_called_out_in_the_rerate_warning(self):
        lines = su.migrate_legacy_floats(_envelope([_v3_finding()])).warnings("r.json")
        rerate = next(ln for ln in lines if "RE-RATE REQUIRED" in ln)
        assert f"defaulted to {su.DEFAULT_MIGRATED_RELEVANCE}" in rerate
        assert "merge_class" in rerate

    def test_id_list_is_truncated(self):
        findings = [_v3_finding(id=f"CODE-{i:03d}") for i in range(1, 15)]
        line = su.migrate_legacy_floats(_envelope(findings)).warnings("r.json")[0]
        assert "(+4 more)" in line
        assert "CODE-014" not in line

    def test_unidentified_finding_still_reported(self):
        f = {"risk": 0.5, "impact": 0.5}
        report = su.migrate_legacy_floats(_envelope([f]))
        assert report.migrated == ["<unidentified>"]

    @pytest.mark.parametrize(
        "hostile",
        [
            "CODE-001\nValid: report.json",
            "CODE-001\r\n[consistency] all clear — no blocking findings",
            "CODE-001\x00\x1b[31m",
        ],
    )
    def test_forged_log_lines_cannot_escape_the_warning(self, hostile):
        """Producer text reaches a stream the coordinator parses, before any
        schema check has constrained it — a newline would forge a record."""
        f = _v3_finding(id=hostile)
        lines = su.migrate_legacy_floats(_envelope([f])).warnings("report.json")
        for line in lines:
            assert "\n" not in line and "\r" not in line
        assert not any(
            ln.lstrip().startswith(("Valid:", "[consistency]")) for ln in lines
        )

    def test_long_identifier_is_truncated(self):
        f = _v3_finding(id="C" * 500)
        report = su.migrate_legacy_floats(_envelope([f]))
        assert len(report.migrated[0]) < 200
        assert report.migrated[0].endswith("…")


class TestRendererApiPathMigrates:
    """Migration lives in `_normalize_report`, which every renderer funnels
    through — not only in the CLI `main()`. An importer calling `render_markdown`
    directly on a v3 CRITICAL used to get INFO: no chips, no warning, no crash.
    """

    def _v3_report(self) -> dict:
        return _envelope([_v3_finding(risk=1.0, impact=1.0, scope=1.0)])

    def test_markdown_renders_the_v4_band(self):
        markdown = grr.render_markdown(self._v3_report())
        assert "(CRITICAL)" in markdown
        assert "likelihood=1.00" in markdown
        assert "(INFO)" not in markdown

    def test_html_renders_the_v4_band_and_chips(self):
        html = grr.render_html(self._v3_report())
        assert 'data-severity="5"' in html
        assert "L 1.00" in html

    def test_triage_renders_the_v4_band(self):
        assert 'data-severity="5"' in grr.render_triage(self._v3_report())

    def test_renderer_warns_about_the_migration(self, caplog):
        with caplog.at_level(logging.WARNING):
            grr.render_markdown(self._v3_report())
        assert "[deprecated]" in caplog.text
        assert "RE-RATE REQUIRED" in caplog.text

    def test_summary_counts_follow_the_recomputed_band(self):
        report = self._v3_report()
        grr.render_markdown(report)
        counts = report["summary_statistics"]["severity_counts"]
        assert counts["CRITICAL"] == 1
        assert counts["INFO"] == 0

    def test_stale_nonzero_counts_are_rebuilt_after_migration(self):
        """The hand-supplied-statistics carve-out must not apply to a migrated
        report: its counts were tallied under the v3 formula, so keeping them
        prints a summary table contradicting the finding bodies below it."""
        report = self._v3_report()
        report["summary_statistics"]["severity_counts"] = {
            "CRITICAL": 0,
            "HIGH": 1,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0,
        }
        grr.render_markdown(report)
        counts = report["summary_statistics"]["severity_counts"]
        assert counts["CRITICAL"] == 1
        assert counts["HIGH"] == 0

    def test_v4_report_keeps_its_hand_supplied_counts(self):
        """The carve-out still holds when nothing was migrated."""
        finding = _v3_finding()
        del finding["risk"], finding["scope"]
        finding.update(likelihood=0.1, relevance=0.1)
        report = _envelope([finding])
        report["summary_statistics"]["severity_counts"]["HIGH"] = 7
        grr.render_markdown(report)
        assert report["summary_statistics"]["severity_counts"]["HIGH"] == 7


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
        assert captured.out.startswith("Valid (after schema-v3 migration;")
        assert "[deprecated]" in captured.err
        assert "RE-RATE REQUIRED" in captured.err

    def test_verdict_does_not_certify_the_on_disk_file(
        self, tmp_path, monkeypatch, capsys
    ):
        """A bare `Valid: <path>` claims the bytes on disk passed. They did not
        — the file is still v3 and the v4 schema rejects it outright."""
        path = tmp_path / "legacy.json"
        path.write_text(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        monkeypatch.setattr(sys, "argv", ["validate_report.py", str(path)])

        assert vr.main() == 0
        out = capsys.readouterr().out
        assert "on-disk file is v3" in out
        assert not out.startswith("Valid: ")

    def test_strict_v4_rejects_a_migrated_file(self, tmp_path, monkeypatch, capsys):
        path = tmp_path / "legacy.json"
        path.write_text(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        monkeypatch.setattr(
            sys, "argv", ["validate_report.py", str(path), "--strict-v4"]
        )

        assert vr.main() == 1
        captured = capsys.readouterr()
        assert "--strict-v4" in captured.err
        assert "Valid" not in captured.out

    def test_strict_v4_accepts_a_clean_v4_report(self, tmp_path, monkeypatch, capsys):
        v4 = ROOT / "tests" / "fixtures" / "reports" / "v4-full.json"
        monkeypatch.setattr(sys, "argv", ["validate_report.py", str(v4), "--strict-v4"])

        assert vr.main() == 0
        assert capsys.readouterr().out.startswith("Valid: ")

    def test_unmigrated_fixture_fails_the_schema(self, tmp_path, monkeypatch, capsys):
        """Proves the shim is what saves it: bypass the migration and the v3
        float names are rejected outright."""
        path = tmp_path / "legacy.json"
        path.write_text(LEGACY_FIXTURE.read_text(encoding="utf-8"))
        monkeypatch.setattr(sys, "argv", ["validate_report.py", str(path)])
        monkeypatch.setattr(
            vr,
            "migrate_legacy_floats",
            lambda data: su.LegacyFloatMigration([], [], [], [], []),
        )

        assert vr.main() == 1
        assert "Validation failed" in capsys.readouterr().err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
