"""Tests for merge_findings_helper.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import merge_findings_helper as helper


def _finding(agent: str, original_id: str, **updates: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "agent": agent,
        "original_id": original_id,
        "category": "security",
        "section_title": "Security",
        "severity": 4,
        "likelihood": 0.7,
        "impact": 0.8,
        "relevance": 0.2,
        "title": f"Finding {original_id}",
        "tags": ["security"],
        "location": "src/example.py:10",
        "description": "Original description.",
        "recommendation": "Fix it.",
    }
    finding.update(updates)
    return finding


def test_apply_cluster_merge_preserves_untouched_findings():
    raw = [
        _finding("security", "SEC-001"),
        _finding("qa", "QA-003", tags=["parser"]),
        _finding("project", "PROJ-002", category="project"),
    ]
    merged = helper.apply_cluster_merge(
        raw,
        reason="Both findings describe the same parser failure.",
        members=[
            {"agent": "security", "original_id": "SEC-001"},
            {"agent": "qa", "original_id": "QA-003"},
        ],
        base={"agent": "security", "original_id": "SEC-001"},
        updates={
            "description": "Merged parser failure description.",
            "tags": ["parser", "security"],
        },
    )

    assert len(merged) == 2
    assert merged[0]["description"] == "Merged parser failure description."
    assert merged[0]["tags"] == ["parser", "security"]
    assert merged[1] == raw[2]
    assert merged[1] is not raw[2]
    assert raw[0]["description"] == "Original description."


def test_apply_cluster_merge_rejects_overlapping_decisions():
    raw = [
        _finding("security", "SEC-001"),
        _finding("qa", "QA-003"),
        _finding("project", "PROJ-002"),
    ]
    decisions = [
        {
            "reason": "First duplicate cluster.",
            "members": [
                {"agent": "security", "original_id": "SEC-001"},
                {"agent": "qa", "original_id": "QA-003"},
            ],
            "base": {"agent": "security", "original_id": "SEC-001"},
            "updates": {"description": "First merge."},
        },
        {
            "reason": "Overlaps the first cluster.",
            "members": [
                {"agent": "security", "original_id": "SEC-001"},
                {"agent": "project", "original_id": "PROJ-002"},
            ],
            "base": {"agent": "security", "original_id": "SEC-001"},
            "updates": {"description": "Overlapping merge."},
        },
    ]

    with pytest.raises(ValueError, match="more than one merge decision"):
        helper.apply_merge_decisions(raw, decisions)


def test_build_merged_document_copies_prepare_data_and_groups_sections():
    intermediate = {
        "metadata": {"project": "claudius", "date": "2026-07-28"},
        "agent_stats": [
            {"agent": "security", "unique": 1, "redundant": 1},
            {"agent": "project", "unique": 1, "redundant": 0},
        ],
        "section_positives": [
            {"category": "security", "agent": "security", "text": "Good validation."},
            {"category": "security", "agent": "qa", "text": "Useful tests."},
        ],
    }
    findings = [
        _finding("security", "SEC-001"),
        _finding("project", "PROJ-002", category="project", section_title="Project"),
    ]
    summary = {"overall_assessment": "Needs changes."}

    document = helper.build_merged_document(intermediate, findings, summary)

    assert document["metadata"] == intermediate["metadata"]
    assert document["agent_stats"] == intermediate["agent_stats"]
    assert document["executive_summary"] == summary
    assert [section["category"] for section in document["findings"]] == [
        "security",
        "project",
    ]
    assert document["findings"][0]["positives"] == ("Good validation.\n\nUseful tests.")
    output_finding = document["findings"][0]["findings"][0]
    assert output_finding["original_id"] == "SEC-001"
    assert "agent" not in output_finding
    assert "category" not in output_finding
    assert "section_title" not in output_finding


def test_main_applies_decisions_and_writes_output(tmp_path):
    intermediate_path = tmp_path / "intermediate.json"
    decisions_path = tmp_path / "merge-decisions.json"
    output_path = tmp_path / "merged-findings.json"
    intermediate_path.write_text(
        json.dumps(
            {
                "metadata": {"project": "claudius", "date": "2026-07-28"},
                "agent_stats": [{"agent": "security", "unique": 0, "redundant": 2}],
                "raw_findings": [
                    _finding("security", "SEC-001"),
                    _finding("qa", "QA-003"),
                ],
                "section_positives": [],
            }
        )
    )
    decisions_path.write_text(
        json.dumps(
            {
                "executive_summary": {"overall_assessment": "Needs changes."},
                "merges": [
                    {
                        "reason": "Same parser failure.",
                        "members": [
                            {"agent": "security", "original_id": "SEC-001"},
                            {"agent": "qa", "original_id": "QA-003"},
                        ],
                        "base": {"agent": "security", "original_id": "SEC-001"},
                        "updates": {"description": "Merged description."},
                    }
                ],
            }
        )
    )

    result = helper.main(
        [
            "--input",
            str(intermediate_path),
            "--decisions",
            str(decisions_path),
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    output = json.loads(output_path.read_text())
    assert output["agent_stats"] == [{"agent": "security", "unique": 0, "redundant": 2}]
    assert output["findings"][0]["findings"][0]["description"] == (
        "Merged description."
    )
