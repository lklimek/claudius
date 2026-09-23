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


@pytest.mark.parametrize(
    "update",
    [
        {"merge_class": "blocking"},
        {"merge_class": "blocking", "intent_basis": "  "},
        {"merge_class": "blocking", "intent_basis": None},
    ],
)
def test_blocking_update_requires_intent_basis(update):
    with pytest.raises(ValueError, match="intent_basis"):
        helper.resolve_findings(
            [_finding("security", "SEC-001")],
            {"finding_updates": {"security:SEC-001": update}},
        )


def test_blocking_update_keeps_producer_intent_basis():
    resolved = helper.resolve_findings(
        [_finding("security", "SEC-001", intent_basis="G-DATA: wipes rows")],
        {"finding_updates": {"security:SEC-001": {"merge_class": "blocking"}}},
    )
    assert resolved[0]["intent_basis"] == "G-DATA: wipes rows"


def test_unblocking_update_clears_stale_intent_basis():
    resolved = helper.resolve_findings(
        [
            _finding(
                "security",
                "SEC-001",
                merge_class="blocking",
                intent_basis="G-DATA: wipes rows",
            )
        ],
        {"finding_updates": {"security:SEC-001": {"merge_class": "non_blocking"}}},
    )
    assert resolved[0]["merge_class"] == "non_blocking"
    assert "intent_basis" not in resolved[0]


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


@pytest.mark.parametrize("bad", [["X"], {"k": 1}, 7, None])
def test_malformed_merge_member_keys_are_value_errors(bad):
    raw = [_finding("security", "SEC-001"), _finding("qa", "QA-003")]
    decisions = {
        "merges": [
            {
                "reason": "Same bug.",
                "members": [
                    {"agent": "security", "original_id": "SEC-001"},
                    {"agent": "qa", "original_id": bad},
                ],
                "base": {"agent": bad, "original_id": "SEC-001"},
                "updates": {},
            }
        ],
        "finding_updates": {"security:SEC-001": {"merge_class": "non_blocking"}},
    }
    with pytest.raises(ValueError):
        helper.resolve_findings(raw, decisions)


@pytest.mark.parametrize("key", ["", ":", "security:", ":SEC-001", "SEC-001"])
def test_malformed_finding_update_keys_are_value_errors(key):
    with pytest.raises(ValueError, match="<agent>:<original_id>"):
        helper.resolve_findings(
            [_finding("security", "SEC-001")],
            {"finding_updates": {key: {"merge_class": "non_blocking"}}},
        )


def _write_cli_inputs(tmp_path, decisions):
    intermediate = tmp_path / "intermediate.json"
    intermediate.write_text(
        json.dumps(
            {
                "agent_stats": [],
                "duplicate_groups": [],
                "raw_findings": [_finding("security", "SEC-001")],
            }
        )
    )
    decisions_path = tmp_path / "merge-decisions.json"
    decisions_path.write_text(json.dumps(decisions))
    return intermediate, decisions_path


def _run_cli(intermediate, decisions_path, output):
    return helper.main(
        ["--input", str(intermediate), "--decisions", str(decisions_path)]
        + ["--output", str(output)]
    )


def test_main_invalid_decision_exits_1_like_finalize(tmp_path):
    update = {"security:SEC-001": {"merge_class": "blocking"}}
    intermediate, decisions = _write_cli_inputs(tmp_path, {"finding_updates": update})
    output = tmp_path / "merged.json"
    assert _run_cli(intermediate, decisions, output) == 1
    assert not output.exists()


def test_main_unreadable_input_exits_2_like_finalize(tmp_path):
    _, decisions = _write_cli_inputs(tmp_path, {})
    assert _run_cli(tmp_path / "nope.json", decisions, tmp_path / "m.json") == 2


@pytest.mark.parametrize(
    "cluster_update",
    [
        {"merge_class": "blocking"},
        {"merge_class": "nonsense"},
        {"likelihood": 2.0},
    ],
)
def test_cluster_updates_cannot_bypass_classification_rules(cluster_update):
    findings = [_finding("security", "SEC-001"), _finding("qa", "QA-001")]
    decisions = {
        "finding_updates": {"security:SEC-001": {"merge_class": "non_blocking"}},
        "merges": [
            {
                "reason": "Same issue.",
                "members": [
                    {"agent": "security", "original_id": "SEC-001"},
                    {"agent": "qa", "original_id": "QA-001"},
                ],
                "base": {"agent": "security", "original_id": "SEC-001"},
                "updates": cluster_update,
            }
        ],
    }
    with pytest.raises(ValueError, match="security:SEC-001"):
        helper.resolve_findings(findings, decisions)


def test_cluster_update_to_blocking_with_intent_basis_is_accepted():
    findings = [_finding("security", "SEC-001"), _finding("qa", "QA-001")]
    decisions = {
        "merges": [
            {
                "reason": "Same issue.",
                "members": [
                    {"agent": "security", "original_id": "SEC-001"},
                    {"agent": "qa", "original_id": "QA-001"},
                ],
                "base": {"agent": "security", "original_id": "SEC-001"},
                "updates": {"merge_class": "blocking", "intent_basis": "G-DATA: x"},
            }
        ],
    }
    [merged] = helper.resolve_findings(findings, decisions)
    assert merged["merge_class"] == "blocking"


def _cluster(updates: dict[str, object]) -> dict[str, object]:
    return {
        "reason": "Same issue.",
        "members": [
            {"agent": "security", "original_id": "SEC-001"},
            {"agent": "qa", "original_id": "QA-001"},
        ],
        "base": {"agent": "security", "original_id": "SEC-001"},
        "updates": updates,
    }


@pytest.mark.parametrize("via_finding_update", [True, False])
def test_cluster_update_unblocking_clears_stale_intent_basis(via_finding_update):
    blocking = {"merge_class": "blocking", "intent_basis": "G-DATA: wipes rows"}
    base = _finding("security", "SEC-001", **({} if via_finding_update else blocking))
    decisions: dict[str, object] = {
        "merges": [_cluster({"merge_class": "non_blocking"})]
    }
    if via_finding_update:
        decisions["finding_updates"] = {"security:SEC-001": blocking}
    [merged] = helper.resolve_findings([base, _finding("qa", "QA-001")], decisions)
    assert merged["merge_class"] == "non_blocking"
    assert "intent_basis" not in merged


def test_cluster_update_keeps_an_explicitly_supplied_intent_basis():
    base = _finding("security", "SEC-001", merge_class="blocking", intent_basis="x")
    updates = {"merge_class": "non_blocking", "intent_basis": "Deferred: see #12"}
    [merged] = helper.resolve_findings(
        [base, _finding("qa", "QA-001")], {"merges": [_cluster(updates)]}
    )
    assert merged["intent_basis"] == "Deferred: see #12"


def test_cluster_update_without_classification_keeps_intent_basis():
    base = _finding("security", "SEC-001", merge_class="blocking", intent_basis="G-X")
    [merged] = helper.resolve_findings(
        [base, _finding("qa", "QA-001")], {"merges": [_cluster({"title": "Merged"})]}
    )
    assert merged["intent_basis"] == "G-X"
