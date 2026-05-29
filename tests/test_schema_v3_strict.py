"""Strict schema acceptance: v3 fixtures pass; v2 is rejected."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr

SCHEMA = json.loads(cr.SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"
LEGACY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy"


class TestV3Minimal:
    def test_passes_schema(self):
        data = json.loads((FIXTURES / "v3-minimal.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]


class TestV3Full:
    def test_passes_schema(self):
        data = json.loads((FIXTURES / "v3-full.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]


class TestProducerShapeAccepted:
    """Producer-emitted findings (no coordinator-derived fields) MUST validate.

    LLMs supply OWASP floats (risk/impact/scope) and the qualitative content
    (title/location/description/recommendation); the coordinator computes
    overall_severity, integer severity, location_permalink, and any AI
    verdict fields on its own pass. The v3 schema therefore must not REQUIRE
    those derived fields — a fresh producer report should validate as-is so
    a skill like check-pr-comments can call validate_report.py on its own
    output without first routing through consolidate_reports.py.
    """

    def _producer_report(self) -> dict:
        return {
            "schema_version": "3.0.0",
            "metadata": {"project": "p", "date": "2026-05-27"},
            "executive_summary": {"overall_assessment": "ok"},
            "summary_statistics": {
                "total_findings": 1,
                "severity_counts": {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 0,
                    "LOW": 1,
                    "INFO": 0,
                },
            },
            "findings": [
                {
                    "title": "Code Quality",
                    "category": "code_quality",
                    "findings": [
                        {
                            "id": "CODE-001",
                            "risk": 0.4,
                            "impact": 0.4,
                            "scope": 1.0,
                            "title": "Producer-shape finding",
                            "location": "src/example.rs:10-20",
                            "description": "A producer-emitted finding with no coordinator fields.",
                            "recommendation": "Coordinator will fill the derived bits later.",
                        }
                    ],
                }
            ],
        }

    def test_producer_shape_finding_passes_schema(self):
        """No `severity`, no `overall_severity`, no `location_permalink`,
        no AI fields — the producer report must still pass v3 validation."""
        data = self._producer_report()
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]

    def test_producer_shape_missing_required_float_is_still_rejected(self):
        """Producer-side fields stay required. Dropping `risk` must fail —
        the coordinator can't derive overall_severity without all three floats."""
        data = self._producer_report()
        del data["findings"][0]["findings"][0]["risk"]
        errors = list(VALIDATOR.iter_errors(data))
        assert (
            errors
        ), "Expected schema to reject finding missing producer-required `risk`"

    def test_producer_shape_missing_required_text_is_still_rejected(self):
        """The qualitative LLM judgements (title/location/description/...) stay required."""
        data = self._producer_report()
        del data["findings"][0]["findings"][0]["description"]
        errors = list(VALIDATOR.iter_errors(data))
        assert (
            errors
        ), "Expected schema to reject finding missing required `description`"


class TestCallTreeCategory:
    """Stream A — the call_tree category and CALL- ID prefix must validate
    end-to-end; unknown prefixes must still be rejected."""

    def test_call_tree_fixture_passes_schema(self):
        data = json.loads((FIXTURES / "v3-call-tree.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]

    def test_call_prefix_finding_validates(self):
        """A standalone finding with id=CALL-001 and category=call_tree
        must pass the v3 schema."""
        report = {
            "schema_version": "3.0.0",
            "metadata": {"project": "p", "date": "2026-05-28"},
            "executive_summary": {"overall_assessment": "ok"},
            "summary_statistics": {
                "total_findings": 1,
                "severity_counts": {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 1,
                    "LOW": 0,
                    "INFO": 0,
                },
            },
            "findings": [
                {
                    "title": "Call-Tree Inspection",
                    "category": "call_tree",
                    "findings": [
                        {
                            "id": "CALL-001",
                            "risk": 0.5,
                            "impact": 0.5,
                            "scope": 1.0,
                            "title": "Walked call chain hides an unbounded loop",
                            "location": "src/walker.rs:42-58",
                            "description": "Following foo -> bar -> baz, baz spins forever on attacker input.",
                            "recommendation": "Add an iteration bound and surface it through the public API.",
                        }
                    ],
                }
            ],
        }
        errors = list(VALIDATOR.iter_errors(report))
        assert errors == [], [e.message for e in errors]

    def test_unknown_id_prefix_is_rejected(self):
        """An id with a prefix not in the schema's alternation must fail."""
        report = {
            "schema_version": "3.0.0",
            "metadata": {"project": "p", "date": "2026-05-28"},
            "executive_summary": {"overall_assessment": "ok"},
            "summary_statistics": {
                "total_findings": 1,
                "severity_counts": {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 1,
                    "LOW": 0,
                    "INFO": 0,
                },
            },
            "findings": [
                {
                    "title": "Security Findings",
                    "category": "security",
                    "findings": [
                        {
                            "id": "XYZ-001",
                            "risk": 0.5,
                            "impact": 0.5,
                            "scope": 1.0,
                            "title": "Bogus prefix",
                            "location": "src/x.rs:1",
                            "description": "d",
                            "recommendation": "r",
                        }
                    ],
                }
            ],
        }
        errors = list(VALIDATOR.iter_errors(report))
        assert errors, "Expected schema to reject finding with unknown id prefix XYZ-"


class TestV31AdditiveFields:
    """Schema 3.1.0 additive bits: pr_audit report_type, finding author_type,
    finding_section verdict. All optional; absence still validates and the
    'severity not required' producer contract stays green."""

    def _base(self) -> dict:
        return {
            "schema_version": "3.1.0",
            "metadata": {"project": "p", "date": "2026-05-29"},
            "executive_summary": {"overall_assessment": "ok"},
            "summary_statistics": {
                "total_findings": 1,
                "severity_counts": {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 0,
                    "LOW": 1,
                    "INFO": 0,
                },
            },
            "findings": [
                {
                    "title": "PR Comments",
                    "category": "pr_comments",
                    "findings": [
                        {
                            "id": "CMT-001",
                            "risk": 0.4,
                            "impact": 0.4,
                            "scope": 1.0,
                            "title": "t",
                            "location": "src/x.py:1",
                            "description": "d",
                            "recommendation": "r",
                        }
                    ],
                }
            ],
        }

    def test_schema_version_3_1_0_validates(self):
        errors = list(VALIDATOR.iter_errors(self._base()))
        assert errors == [], [e.message for e in errors]

    def test_report_type_pr_audit_validates(self):
        data = self._base()
        data["metadata"]["report_type"] = "pr_audit"
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]

    def test_author_type_bot_and_human_validate(self):
        for value in ("bot", "human"):
            data = self._base()
            data["findings"][0]["findings"][0]["author_type"] = value
            errors = list(VALIDATOR.iter_errors(data))
            assert errors == [], (value, [e.message for e in errors])

    def test_author_type_invalid_rejected(self):
        data = self._base()
        data["findings"][0]["findings"][0]["author_type"] = "robot"
        assert list(VALIDATOR.iter_errors(data)), "invalid author_type must fail"

    def test_finding_section_verdict_values_validate(self):
        for value in ("PASS", "FAIL", "NEEDS_REVIEW"):
            data = self._base()
            data["findings"][0]["verdict"] = value
            errors = list(VALIDATOR.iter_errors(data))
            assert errors == [], (value, [e.message for e in errors])

    def test_finding_section_verdict_invalid_rejected(self):
        data = self._base()
        data["findings"][0]["verdict"] = "MAYBE"
        assert list(VALIDATOR.iter_errors(data)), "invalid section verdict must fail"

    def test_severity_still_not_required(self):
        """Belt-and-braces: a 3.1.0 producer finding with no integer severity
        must still validate (severity stays optional)."""
        data = self._base()
        assert "severity" not in data["findings"][0]["findings"][0]
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]


class TestV2Legacy:
    def test_rejected(self):
        data = json.loads((LEGACY_FIXTURES / "v2-legacy.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors, "Expected v2 fixture to fail v3 schema validation"

    def test_consolidate_rejects_v2_input(self, tmp_path, caplog):
        """An agent report carrying schema_version != 3.0.0 must be rejected
        loudly with a version-aware error message that points at the schema."""
        legacy = {"schema_version": "2.0.0", "sections": []}
        rep = tmp_path / "legacy.json"
        rep.write_text(json.dumps(legacy))
        import argparse
        import logging

        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(tmp_path / "out.json"),
            metadata=None,
        )
        with caplog.at_level(logging.ERROR):
            rc = cr.cmd_prepare(args)
        assert rc != 0
        # Error message must mention schema_version and the expected value,
        # not just "expected JSON array".
        joined = "\n".join(r.message for r in caplog.records)
        assert "schema_version" in joined
        assert "3.0.0" in joined

    def test_consolidate_rejects_v1_envelope(self, tmp_path, caplog):
        """A v1-shaped envelope (schema_version = 1.x) must also be rejected
        with the same version-aware message."""
        legacy = {"schema_version": "1.0.0", "findings": []}
        rep = tmp_path / "legacy.json"
        rep.write_text(json.dumps(legacy))
        import argparse
        import logging

        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(tmp_path / "out.json"),
            metadata=None,
        )
        with caplog.at_level(logging.ERROR):
            rc = cr.cmd_prepare(args)
        assert rc != 0
        joined = "\n".join(r.message for r in caplog.records)
        assert "schema_version" in joined


class TestFormatChecker:
    """SEC-005 — jsonschema 4.x does not enforce `format: uri` by default.
    The validators must opt in via format_checker=. As belt-and-braces, the
    schema also pins location_permalink with `pattern: ^https?://` so a
    non-http(s) URI is rejected even when format checking is off / lenient."""

    def test_consolidate_validator_uses_format_checker(self):
        """The consolidate validator must be built with a format checker so
        format constraints are evaluated (not silently ignored)."""
        import inspect
        import consolidate_reports as cr_mod

        src = inspect.getsource(cr_mod._validate_report)
        assert "format_checker" in src, (
            "consolidate_reports._validate_report must construct its "
            "validator with format_checker= to enforce schema format clauses."
        )

    def test_generate_review_report_validator_uses_format_checker(self):
        """The renderer-side validator must also opt in to format checking."""
        import inspect
        import generate_review_report as grr_mod

        # _validate is internally defined inside main(); pick the
        # canonical Validate function instead.
        src = inspect.getsource(grr_mod)
        # We expect at least one Draft202012Validator constructed with
        # format_checker=.
        assert "format_checker=" in src, (
            "generate_review_report must construct validators with "
            "format_checker= so format clauses are enforced."
        )

    def test_validate_report_helper_rejects_javascript_permalink(self):
        """The schema's `pattern: ^https?://` on location_permalink must
        reject javascript: and other non-http(s) URIs via _validate_report."""
        import consolidate_reports as cr_mod
        import json as _json

        data = _json.loads((FIXTURES / "v3-minimal.json").read_text())
        data["findings"][0]["findings"][0]["location_permalink"] = "javascript:alert(1)"
        assert cr_mod._validate_report(data) is False

    def test_validate_report_helper_rejects_non_uri_permalink(self):
        """The schema must reject obviously non-URI values."""
        import consolidate_reports as cr_mod
        import json as _json

        data = _json.loads((FIXTURES / "v3-minimal.json").read_text())
        data["findings"][0]["findings"][0]["location_permalink"] = "not even close"
        assert cr_mod._validate_report(data) is False
