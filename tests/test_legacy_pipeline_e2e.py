"""End-to-end regression: a schema-v3 producer array through the real pipeline.

Every other migration test exercises one stage. This drives an actual v3-shaped
agent report through `prepare` -> merge -> `assemble` -> render and asserts the
finding arrives with v4 floats, the v4 band, and no legacy name anywhere — the
path a real in-flight report takes, which nothing pinned before.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import consolidate_reports as cr  # noqa: E402
import generate_review_report as grr  # noqa: E402
import merge_findings_helper as mfh  # noqa: E402

# A pre-existing catastrophe: certain to be hit, irreversible, barely related to
# the PR. v3 banded it HIGH ((1.0+1.0+0.1)/3 = 0.70); v4 bands it CRITICAL.
V3_AGENT_REPORT = [
    {
        "title": "Security Findings",
        "category": "security",
        "findings": [
            {
                "id": "SEC-001",
                "risk": 1.0,
                "impact": 1.0,
                "scope": 0.1,
                "severity": 4,
                "overall_severity": 0.7,
                "title": "Seed phrase written to the debug log",
                "location": "src/wallet/import.rs:88",
                "description": "The importer logs the mnemonic at debug level.",
                "recommendation": "Redact the mnemonic before logging.",
            }
        ],
    }
]


@pytest.fixture
def report(tmp_path: Path) -> dict:
    """Drive the v3 agent report through the real prepare/merge/assemble stages."""
    agent = tmp_path / "agent.json"
    agent.write_text(json.dumps(V3_AGENT_REPORT), encoding="utf-8")

    intermediate_path = tmp_path / "intermediate.json"
    assert (
        cr.cmd_prepare(
            argparse.Namespace(
                agent_reports=[f"security-engineer:{agent}"],
                repo_root=str(tmp_path),
                output=str(intermediate_path),
                metadata=json.dumps({"project": "claudius", "date": "2026-07-31"}),
            )
        )
        == 0
    )

    # Stand in for the coordinator's merge pass: no duplicate decisions to apply.
    intermediate = mfh.load_intermediate(intermediate_path)
    merged = tmp_path / "merged.json"
    mfh.write_merged_findings(
        merged,
        mfh.build_merged_document(
            intermediate,
            mfh.load_raw_findings(intermediate),
            {"overall_assessment": "e2e fixture"},
        ),
    )

    out = tmp_path / "report.json"
    assert cr.cmd_assemble(argparse.Namespace(input=str(merged), output=str(out))) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _only_finding(report: dict) -> dict:
    return report["findings"][0]["findings"][0]


def test_assembled_report_is_v4(report):
    assert report["schema_version"] == cr.SCHEMA_VERSION


def test_floats_arrive_under_the_v4_names(report):
    finding = _only_finding(report)
    assert finding["likelihood"] == 1.0
    assert finding["impact"] == 1.0
    assert "risk" not in finding and "scope" not in finding


def test_stale_v3_band_does_not_survive_the_pipeline(report):
    finding = _only_finding(report)
    assert finding["severity"] == 5
    assert finding["overall_severity"] == 1.0
    assert report["summary_statistics"]["severity_counts"]["CRITICAL"] == 1
    assert report["summary_statistics"]["severity_counts"]["HIGH"] == 0


def test_top_findings_carry_the_recomputed_band(report):
    assert report["top_findings"][0]["severity"] == 5


def test_no_legacy_name_survives_anywhere(report):
    serialized = json.dumps(report)
    assert '"risk"' not in serialized
    assert '"scope"' not in serialized


def test_renderers_agree_with_the_recomputed_band(report):
    markdown = grr.render_markdown(report)
    assert "(CRITICAL)" in markdown
    assert "likelihood=1.00" in markdown
    assert "(HIGH)" not in markdown

    html = grr.render_html(report)
    assert 'data-severity="5"' in html
    assert "L 1.00" in html


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
