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
                "finding_updates": {
                    "security:SEC-001": {"merge_class": "non_blocking"}
                },
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


# ---------------------------------------------------------------------------
# finding_updates: per-finding merge_class / float overrides
# ---------------------------------------------------------------------------
def test_resolve_findings_applies_per_finding_updates():
    raw = [_finding("security", "SEC-001"), _finding("qa", "QA-003")]
    resolved = helper.resolve_findings(
        raw,
        {
            "finding_updates": {
                "security:SEC-001": {
                    "merge_class": "blocking",
                    "intent_basis": "G-SECRET: token logged at src/example.py:10",
                    "likelihood": 0.9,
                },
                "qa:QA-003": {"merge_class": "non_blocking", "relevance": 0.4},
            }
        },
    )
    assert resolved[0]["merge_class"] == "blocking"
    assert resolved[0]["intent_basis"].startswith("G-SECRET:")
    assert resolved[0]["likelihood"] == 0.9
    assert resolved[1]["merge_class"] == "non_blocking"
    assert resolved[1]["relevance"] == 0.4
    assert "merge_class" not in raw[0]


def test_resolve_findings_applies_updates_before_cluster_merge():
    raw = [_finding("security", "SEC-001"), _finding("qa", "QA-003")]
    resolved = helper.resolve_findings(
        raw,
        {
            "merges": [
                {
                    "reason": "Same bug.",
                    "members": [
                        {"agent": "security", "original_id": "SEC-001"},
                        {"agent": "qa", "original_id": "QA-003"},
                    ],
                    "base": {"agent": "security", "original_id": "SEC-001"},
                    "updates": {"description": "Merged."},
                }
            ],
            "finding_updates": {"security:SEC-001": {"merge_class": "non_blocking"}},
        },
    )
    assert len(resolved) == 1
    assert resolved[0]["merge_class"] == "non_blocking"
    assert resolved[0]["description"] == "Merged."


def test_finding_update_on_merged_away_member_is_rejected():
    raw = [_finding("security", "SEC-001"), _finding("qa", "QA-003")]
    with pytest.raises(ValueError, match="qa:QA-003.*merged away"):
        helper.resolve_findings(
            raw,
            {
                "merges": [
                    {
                        "reason": "Same bug.",
                        "members": [
                            {"agent": "security", "original_id": "SEC-001"},
                            {"agent": "qa", "original_id": "QA-003"},
                        ],
                        "base": {"agent": "security", "original_id": "SEC-001"},
                        "updates": {},
                    }
                ],
                "finding_updates": {"qa:QA-003": {"merge_class": "blocking"}},
            },
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"nobody:X-1": {"merge_class": "blocking"}}, "unknown finding"),
        ({"SEC-001": {"merge_class": "blocking"}}, "<agent>:<original_id>"),
        ({"security:SEC-001": {"title": "x"}}, "unsupported field"),
        ({"security:SEC-001": {"merge_class": "maybe"}}, "merge_class"),
        ({"security:SEC-001": {"likelihood": 1.5}}, "likelihood"),
        ({"security:SEC-001": {"impact": True}}, "impact"),
        ({"security:SEC-001": {"intent_basis": 3}}, "intent_basis"),
        ({"security:SEC-001": "blocking"}, "must be an object"),
    ],
)
def test_invalid_finding_updates_are_rejected(updates, message):
    with pytest.raises(ValueError, match=message):
        helper.resolve_findings(
            [_finding("security", "SEC-001")], {"finding_updates": updates}
        )


def test_original_id_containing_colon_is_addressable():
    resolved = helper.resolve_findings(
        [_finding("security", "SEC:001")],
        {"finding_updates": {"security:SEC:001": {"merge_class": "disputed"}}},
    )
    assert resolved[0]["merge_class"] == "disputed"


def test_find_missing_merge_class_lists_every_unclassified_finding():
    findings = [
        _finding("security", "SEC-001", merge_class="blocking"),
        _finding("qa", "QA-003"),
        _finding("project", "PROJ-002"),
    ]
    assert helper.find_missing_merge_class(findings) == [
        "qa:QA-003",
        "project:PROJ-002",
    ]


def test_main_fails_listing_findings_without_merge_class(tmp_path, caplog):
    intermediate_path = tmp_path / "intermediate.json"
    decisions_path = tmp_path / "merge-decisions.json"
    output_path = tmp_path / "merged-findings.json"
    intermediate_path.write_text(
        json.dumps(
            {
                "metadata": {"project": "claudius", "date": "2026-07-28"},
                "raw_findings": [
                    _finding("security", "SEC-001"),
                    _finding("qa", "QA-003"),
                ],
            }
        )
    )
    decisions_path.write_text(
        json.dumps(
            {"finding_updates": {"security:SEC-001": {"merge_class": "non_blocking"}}}
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

    assert result == 1
    [missing] = [r.message for r in caplog.records if "lack merge_class" in r.message]
    assert "qa:QA-003" in missing
    assert "security:SEC-001" not in missing
    assert not output_path.exists()
