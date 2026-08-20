#!/usr/bin/env python3
"""Build merged-findings.json from prepare output and manual merge decisions.

The decisions file keeps duplicate resolution review-specific while this helper
handles copying untouched findings, applying each hand-authored cluster update,
grouping findings into sections, and preserving prepare's agent statistics.

Usage:
    python3 scripts/merge_findings_helper.py \
        --input intermediate.json \
        --decisions merge-decisions.json \
        --output merged-findings.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from severity_util import load_json_strict

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

FindingKey = tuple[str, str]
_INTERMEDIATE_ONLY_FIELDS = {"agent", "category", "section_title", "positives"}


def _load_json(path: Path) -> Any:
    """Load JSON from path and report parse errors as ValueError.

    Uses the same non-finite guards as every other report loader: this helper
    sits mid-pipeline between ``prepare`` and ``assemble``, so a NaN or an
    overflowing literal skipping the guard here reaches ``assemble`` as an
    already-laundered float.
    """
    try:
        return load_json_strict(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}")
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error


def load_intermediate(path: Path) -> dict[str, Any]:
    """Load and minimally validate consolidate_reports.py prepare output."""
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    raw_findings = data.get("raw_findings")
    if not isinstance(raw_findings, list) or not all(
        isinstance(finding, dict) for finding in raw_findings
    ):
        raise ValueError(f"Expected raw_findings to be an array of objects in {path}")
    return data


def load_raw_findings(intermediate: dict[str, Any]) -> list[dict[str, Any]]:
    """Return shallow copies of every raw finding in prepare output."""
    raw_findings = intermediate.get("raw_findings")
    if not isinstance(raw_findings, list) or not all(
        isinstance(finding, dict) for finding in raw_findings
    ):
        raise ValueError("Expected raw_findings to be an array of objects")
    return [dict(finding) for finding in raw_findings]


def load_decisions(path: Path) -> dict[str, Any]:
    """Load the coordinator-authored merge decisions object."""
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    merges = data.get("merges", [])
    if not isinstance(merges, list) or not all(
        isinstance(decision, dict) for decision in merges
    ):
        raise ValueError(f"Expected merges to be an array of objects in {path}")
    return data


def _finding_key(value: dict[str, Any], *, context: str) -> FindingKey:
    """Extract an (agent, original_id) key from a finding or reference."""
    agent = value.get("agent")
    original_id = value.get("original_id")
    if not isinstance(agent, str) or not agent:
        raise ValueError(f"{context}: agent must be a non-empty string")
    if not isinstance(original_id, str) or not original_id:
        raise ValueError(f"{context}: original_id must be a non-empty string")
    return agent, original_id


def apply_cluster_merge(
    findings: list[dict[str, Any]],
    *,
    members: list[dict[str, Any]],
    base: dict[str, Any],
    updates: dict[str, Any],
    reason: str,
) -> list[dict[str, Any]]:
    """Replace one duplicate cluster with an updated shallow copy of its base."""
    return apply_merge_decisions(
        findings,
        [
            {
                "members": members,
                "base": base,
                "updates": updates,
                "reason": reason,
            }
        ],
    )


def apply_merge_decisions(
    findings: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply manual duplicate-cluster decisions while preserving input order."""
    copies = [dict(finding) for finding in findings]
    findings_by_key: dict[FindingKey, dict[str, Any]] = {}
    for index, finding in enumerate(copies):
        key = _finding_key(finding, context=f"raw finding #{index}")
        if key in findings_by_key:
            raise ValueError(f"Duplicate raw finding key: {key!r}")
        findings_by_key[key] = finding

    decisions_by_member: dict[FindingKey, tuple[FindingKey, dict[str, Any]]] = {}
    for index, decision in enumerate(decisions):
        context = f"merge decision #{index}"
        members_value = decision.get("members")
        if not isinstance(members_value, list) or len(members_value) < 2:
            raise ValueError(f"{context}: members must contain at least two findings")
        if not all(isinstance(member, dict) for member in members_value):
            raise ValueError(f"{context}: every member must be an object")
        members = [
            _finding_key(member, context=f"{context} member")
            for member in members_value
        ]
        if len(set(members)) != len(members):
            raise ValueError(f"{context}: members must be unique")

        base_value = decision.get("base")
        if not isinstance(base_value, dict):
            raise ValueError(f"{context}: base must be an object")
        base = _finding_key(base_value, context=f"{context} base")
        if base not in members:
            raise ValueError(f"{context}: base must also appear in members")

        updates = decision.get("updates")
        if not isinstance(updates, dict):
            raise ValueError(f"{context}: updates must be an object")
        protected = {"agent", "original_id"}.intersection(updates)
        if protected:
            raise ValueError(
                f"{context}: updates cannot replace {', '.join(sorted(protected))}"
            )
        reason = decision.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{context}: reason must be a non-empty string")

        for member in members:
            if member not in findings_by_key:
                raise ValueError(f"{context}: unknown finding {member!r}")
            if member in decisions_by_member:
                raise ValueError(
                    f"Finding {member!r} appears in more than one merge decision"
                )
            decisions_by_member[member] = (base, updates)

    merged: list[dict[str, Any]] = []
    for finding in copies:
        key = _finding_key(finding, context="raw finding")
        decision = decisions_by_member.get(key)
        if decision is None:
            merged.append(finding)
            continue
        base, updates = decision
        if key == base:
            finding.update(updates)
            merged.append(finding)
    return merged


def _section_positives(intermediate: dict[str, Any]) -> dict[str, str]:
    """Combine unique positive observations by finding category."""
    combined: dict[str, list[str]] = {}
    values = intermediate.get("section_positives", [])
    if not isinstance(values, list):
        return {}
    for value in values:
        if not isinstance(value, dict):
            continue
        category = value.get("category")
        text = value.get("text")
        if not isinstance(category, str) or not isinstance(text, str) or not text:
            continue
        texts = combined.setdefault(category, [])
        if text not in texts:
            texts.append(text)
    return {category: "\n\n".join(texts) for category, texts in combined.items()}


def build_merged_document(
    intermediate: dict[str, Any],
    findings: list[dict[str, Any]],
    executive_summary: dict[str, Any],
    *,
    top_findings_override: Any = None,
    remediation_override: Any = None,
) -> dict[str, Any]:
    """Build the merged-findings.json object consumed by assemble."""
    sections: dict[str, dict[str, Any]] = {}
    positives = _section_positives(intermediate)
    for finding in findings:
        category = finding.get("category", "code_quality")
        if not isinstance(category, str):
            raise ValueError("Finding category must be a string")
        section_title = (
            finding.get("section_title") or category.replace("_", " ").title()
        )
        section = sections.setdefault(
            category,
            {
                "title": section_title,
                "category": category,
                "findings": [],
            },
        )
        output_finding = dict(finding)
        for field in _INTERMEDIATE_ONLY_FIELDS:
            output_finding.pop(field, None)
        section["findings"].append(output_finding)

    for category, section in sections.items():
        if category in positives:
            section["positives"] = positives[category]

    metadata = intermediate.get("metadata", {})
    agent_stats = intermediate.get("agent_stats", [])
    if not isinstance(metadata, dict):
        raise ValueError("Expected metadata to be an object")
    if not isinstance(agent_stats, list):
        raise ValueError("Expected agent_stats to be an array")
    if not isinstance(executive_summary, dict):
        raise ValueError("Expected executive_summary to be an object")

    return {
        "metadata": metadata,
        "executive_summary": executive_summary,
        "findings": list(sections.values()),
        "agent_stats": agent_stats,
        "top_findings_override": top_findings_override,
        "remediation_override": remediation_override,
    }


def write_merged_findings(path: Path, document: dict[str, Any]) -> None:
    """Write a merged-findings document as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Apply manual duplicate merges to consolidate prepare output."
    )
    parser.add_argument("--input", required=True, help="Path to intermediate.json")
    parser.add_argument(
        "--decisions",
        required=True,
        help="Path to the coordinator-authored merge decisions JSON",
    )
    parser.add_argument("--output", required=True, help="Output merged-findings path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the merge helper CLI."""
    args = parse_args(argv)
    try:
        intermediate = load_intermediate(Path(args.input))
        decisions = load_decisions(Path(args.decisions))
        findings = apply_merge_decisions(
            load_raw_findings(intermediate), decisions.get("merges", [])
        )
        document = build_merged_document(
            intermediate,
            findings,
            decisions.get("executive_summary", {"overall_assessment": ""}),
            top_findings_override=decisions.get("top_findings_override"),
            remediation_override=decisions.get("remediation_override"),
        )
        write_merged_findings(Path(args.output), document)
    except (FileNotFoundError, ValueError) as error:
        log.error("%s", error)
        return 2

    log.info("Wrote merged findings: %s (%d findings)", args.output, len(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
