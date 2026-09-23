#!/usr/bin/env python3
"""Build merged-findings.json from prepare output and manual merge decisions.

The decisions file keeps duplicate resolution review-specific while this helper
handles copying untouched findings, applying per-finding overrides
(``finding_updates``) and each hand-authored cluster update, grouping findings
into sections, and preserving prepare's agent statistics. The CLI refuses to
write output while any finding still lacks ``merge_class``.

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
import math
import sys
from pathlib import Path
from typing import Any

from severity_util import MERGE_CLASS_ORDER, load_json_strict

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

FindingKey = tuple[str, str]
_INTERMEDIATE_ONLY_FIELDS = {"agent", "category", "section_title", "positives"}
_FLOAT_FIELDS = ("likelihood", "impact", "relevance")
# Used when merge decisions omit executive_summary (the schema requires the key).
DEFAULT_EXECUTIVE_SUMMARY: dict[str, str] = {"overall_assessment": ""}
# The per-finding override table carries judgment only — classification and
# re-rated floats. Text edits belong to a cluster merge's ``updates``.
_FINDING_UPDATE_FIELDS = frozenset({"merge_class", "intent_basis", *_FLOAT_FIELDS})


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
            _drop_stale_intent_basis(finding, updates)
            merged.append(finding)
    return merged


def _key_label(key: FindingKey) -> str:
    """Render a finding key in the ``<agent>:<original_id>`` form used in files."""
    return f"{key[0]}:{key[1]}"


def _parse_update_key(label: Any) -> FindingKey:
    """Parse an ``<agent>:<original_id>`` label; the ID may itself contain ':'."""
    agent, sep, original_id = (label if isinstance(label, str) else "").partition(":")
    if not sep or not agent or not original_id:
        raise ValueError(
            f"finding_updates key {label!r} must be '<agent>:<original_id>'"
        )
    return agent, original_id


def _validate_finding_update(label: str, update: Any) -> dict[str, Any]:
    """Check one finding_updates entry against the allowed fields and types."""
    if not isinstance(update, dict):
        raise ValueError(f"finding_updates[{label!r}] must be an object")
    unsupported = sorted(set(update) - _FINDING_UPDATE_FIELDS)
    if unsupported:
        raise ValueError(
            f"finding_updates[{label!r}]: unsupported field(s) "
            f"{', '.join(unsupported)}; allowed: "
            f"{', '.join(sorted(_FINDING_UPDATE_FIELDS))}"
        )
    merge_class = update.get("merge_class")
    if "merge_class" in update and merge_class not in MERGE_CLASS_ORDER:
        raise ValueError(
            f"finding_updates[{label!r}]: merge_class must be one of "
            f"{', '.join(MERGE_CLASS_ORDER)}"
        )
    intent_basis = update.get("intent_basis")
    if intent_basis is not None and not isinstance(intent_basis, str):
        raise ValueError(
            f"finding_updates[{label!r}]: intent_basis must be a string or null"
        )
    for field in _FLOAT_FIELDS:
        if field not in update:
            continue
        value = update[field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
        ):
            raise ValueError(
                f"finding_updates[{label!r}]: {field} must be a number in [0, 1]"
            )
    return update


def _key_or_none(ref: Any) -> FindingKey | None:
    """Return ``(agent, original_id)`` when both are strings, else None."""
    if not isinstance(ref, dict):
        return None
    agent, original_id = ref.get("agent"), ref.get("original_id")
    if isinstance(agent, str) and isinstance(original_id, str):
        return agent, original_id
    return None


def resolve_findings(
    findings: list[dict[str, Any]], decisions: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply ``finding_updates`` then cluster ``merges`` to copies of findings.

    Per-finding updates land first so a cluster's hand-authored ``updates``
    win on conflict. Updating a non-base cluster member is an error: that
    finding is dropped by the merge, so the judgment would silently vanish.
    """
    updates_value = decisions.get("finding_updates", {})
    if not isinstance(updates_value, dict):
        raise ValueError("finding_updates must be an object")
    merges = decisions.get("merges", [])
    if not isinstance(merges, list):
        raise ValueError("merges must be an array")

    copies = [dict(finding) for finding in findings]
    by_key = {
        _finding_key(finding, context=f"raw finding #{index}"): finding
        for index, finding in enumerate(copies)
    }
    # Pre-scan only; apply_merge_decisions validates and reports malformed
    # entries, so skip anything that is not a well-formed key here.
    merged_away: set[FindingKey] = set()
    for decision in merges:
        if not isinstance(decision, dict):
            continue
        base_key = _key_or_none(decision.get("base"))
        members = decision.get("members")
        for member in members if isinstance(members, list) else []:
            key = _key_or_none(member)
            if key is not None and key != base_key:
                merged_away.add(key)

    for label, update in updates_value.items():
        key = _parse_update_key(label)
        _validate_finding_update(label, update)
        if key not in by_key:
            raise ValueError(f"finding_updates: unknown finding {label!r}")
        if key in merged_away:
            raise ValueError(
                f"finding_updates: {label!r} is merged away by a cluster merge; "
                "update the cluster base instead"
            )
        _apply_finding_update(by_key[key], label, update)

    resolved = apply_merge_decisions(copies, merges)
    for finding in resolved:
        _check_classification(finding)
    return resolved


def _check_classification(finding: dict[str, Any]) -> None:
    """Re-check classification and rating fields after cluster ``updates``.

    Cluster updates may set any field, so the finding_updates rules are
    re-applied to the result: valid merge_class and floats, and ``blocking``
    only with an intent_basis.
    """
    label = f"{finding.get('agent')}:{finding.get('original_id')}"
    rated = {k: finding[k] for k in _FINDING_UPDATE_FIELDS if k in finding}
    _validate_finding_update(label, rated)
    basis = finding.get("intent_basis")
    if finding.get("merge_class") == "blocking" and not (
        isinstance(basis, str) and basis.strip()
    ):
        raise ValueError(f"{label}: merge_class blocking requires an intent_basis")


def _apply_finding_update(
    finding: dict[str, Any], label: str, update: dict[str, Any]
) -> None:
    """Apply one update, keeping ``intent_basis`` consistent with ``merge_class``.

    ``blocking`` must carry an intent_basis (gate + evidence); moving off
    ``blocking`` without a new intent_basis drops the now-stale one.
    """
    finding.update(update)
    if "merge_class" not in update and "intent_basis" not in update:
        return
    if finding.get("merge_class") == "blocking":
        basis = finding.get("intent_basis")
        if not isinstance(basis, str) or not basis.strip():
            raise ValueError(
                f"finding_updates[{label!r}]: blocking requires a non-empty "
                "intent_basis (gate ID plus evidence)"
            )
    _drop_stale_intent_basis(finding, update)


def _drop_stale_intent_basis(finding: dict[str, Any], update: dict[str, Any]) -> None:
    """Drop ``intent_basis`` when ``update`` leaves the finding non-blocking.

    Applies only when ``update`` touches the classification and supplies no
    new intent_basis; shared by finding_updates and cluster ``updates``.
    """
    touched = "merge_class" in update or "intent_basis" in update
    if (
        touched
        and finding.get("merge_class") != "blocking"
        and update.get("intent_basis") is None
    ):
        finding.pop("intent_basis", None)


def find_missing_merge_class(findings: list[dict[str, Any]]) -> list[str]:
    """Return ``<agent>:<original_id>`` for every finding lacking merge_class."""
    return [
        _key_label(_finding_key(finding, context="finding"))
        for finding in findings
        if finding.get("merge_class") not in MERGE_CLASS_ORDER
    ]


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
    except (OSError, ValueError) as error:
        log.error("%s", error)
        return 2
    try:
        findings = resolve_findings(load_raw_findings(intermediate), decisions)
        missing = find_missing_merge_class(findings)
        if missing:
            log.error(
                "%d finding(s) lack merge_class — add them to finding_updates: %s",
                len(missing),
                ", ".join(missing),
            )
            return 1
        document = build_merged_document(
            intermediate,
            findings,
            decisions.get("executive_summary", dict(DEFAULT_EXECUTIVE_SUMMARY)),
            top_findings_override=decisions.get("top_findings_override"),
            remediation_override=decisions.get("remediation_override"),
        )
    except ValueError as error:
        log.error("%s", error)
        return 1
    write_merged_findings(Path(args.output), document)

    log.info("Wrote merged findings: %s (%d findings)", args.output, len(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
