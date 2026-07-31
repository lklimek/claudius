#!/usr/bin/env python3
"""Shared severity derivation and statistics helpers.

Single source of truth for the severity band table, the per-finding
severity derivation (mean of likelihood/impact mapped to a band), the
schema-v3 float migration, and the summary-statistics / category-matrix
builder. Both the coordinator (``consolidate_reports.py``) and the renderer
(``generate_review_report.py``) import from here so the math lives in
exactly one place.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any, NamedTuple


def reject_non_finite_constant(constant: str) -> Any:
    """json ``parse_constant`` callback: reject bare NaN/Infinity/-Infinity.

    Python's ``json`` module decodes these non-finite literals by default. They
    slip past ``isinstance(x, float)`` and range checks (``nan >= t`` is always
    False; ``jsonschema`` min/max treats NaN as valid), silently corrupting
    severity math. Wiring this into every report-loading ``json.loads`` rejects
    them at parse time with a clear error instead.
    """
    raise ValueError(f"non-finite JSON constant not allowed: {constant}")


SEV_LABELS: dict[int, str] = {
    5: "CRITICAL",
    4: "HIGH",
    3: "MEDIUM",
    2: "LOW",
    1: "INFO",
}
SEV_ORDER: list[str] = list(SEV_LABELS.values())  # CRITICAL, HIGH, ... INFO

MERGE_CLASS_LABELS: dict[str, str] = {
    "blocking": "BLOCKING",
    "non_blocking": "NON-BLOCKING",
    "out_of_scope_follow_up": "FOLLOW-UP",
    "disputed": "DISPUTED",
}
MERGE_CLASS_ORDER: list[str] = [
    "blocking",
    "non_blocking",
    "out_of_scope_follow_up",
    "disputed",
]
MERGE_CLASS_COLORS: dict[str, str] = {
    "blocking": "#C0392B",
    "non_blocking": "#D4AC0D",
    "out_of_scope_follow_up": "#607D8B",
    "disputed": "#7F8C8D",
}
MERGE_CLASS_TEXT_COLORS: dict[str, str] = {
    "blocking": "#FFFFFF",
    "non_blocking": "#0A0A0A",
    "out_of_scope_follow_up": "#0A0A0A",
    "disputed": "#0A0A0A",
}

# Categories tracked in the severity x category matrix. Mirrors the
# coordinator's CATEGORY_PREFIX ordering.
MATRIX_CATEGORIES: list[str] = [
    "security",
    "project",
    "code_quality",
    "call_tree",
    "documentation",
    "pr_comments",
    "pr_promises",
    "dependencies",
]

# Band table — CVSS v4.0-aligned thresholds, applied descending.
_SEVERITY_BANDS: list[tuple[float, int]] = [
    (0.9, 5),
    (0.7, 4),
    (0.4, 3),
    (0.1, 2),
]
_SEVERITY_EPSILON = 1e-9


# Dimensions of the severity mean. ``relevance`` is deliberately excluded: it
# rates fit to the PR's goal, not how bad the defect is, so averaging it in
# launders a pre-existing catastrophe (likelihood 1.0, impact 1.0,
# relevance 0.1) down to MEDIUM.
_SEVERITY_DIMENSIONS: tuple[str, ...] = ("likelihood", "impact")


def derive_overall(finding: dict[str, Any]) -> float | None:
    """Arithmetic mean of likelihood + impact when both are finite floats.

    Returns None when either dimension is absent, non-numeric, or non-finite
    (NaN/Infinity) — NaN would sink a CRITICAL finding to INFO and +Infinity
    would force it to CRITICAL regardless of the other dimension.
    """
    dims = []
    for key in _SEVERITY_DIMENSIONS:
        value = finding.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        if math.isnan(value) or math.isinf(value):
            return None
        dims.append(float(value))
    return sum(dims) / len(_SEVERITY_DIMENSIONS)


def derive_severity_int(overall: float) -> int:
    """Map an overall_severity float to the 1..5 integer severity band."""
    for threshold, level in _SEVERITY_BANDS:
        if overall >= threshold - _SEVERITY_EPSILON:
            return level
    return 1


def derive_finding_severity(finding: dict[str, Any]) -> int | None:
    """Return the integer band for a finding carrying likelihood and impact.

    Returns None when either float is absent or non-numeric, signalling the
    caller to fall back to an explicit ``severity`` (or INFO).
    """
    overall = derive_overall(finding)
    if overall is None:
        return None
    return derive_severity_int(overall)


def _effective_severity(finding: dict[str, Any]) -> int:
    """Resolve a finding's integer severity for counting.

    Prefers the band derived from the likelihood/impact floats — per the
    severity skill's doctrine, the floats are the single source of truth,
    so a derived band wins even over a conflicting explicit integer
    ``severity`` (matching ``cmd_assemble``'s precedence in
    ``consolidate_reports.py``). Falls back to the explicit integer when the
    floats are absent or invalid, then to 1 (INFO) when neither is available.
    """
    derived = derive_finding_severity(finding)
    if derived is not None:
        return derived
    sev = finding.get("severity")
    if isinstance(sev, int) and not isinstance(sev, bool) and 1 <= sev <= 5:
        return sev
    return 1


# ---------------------------------------------------------------------------
# Schema-v3 float migration (deprecated read path)
# ---------------------------------------------------------------------------
# v3 findings carried ``risk``/``impact``/``scope``. v4 carries
# ``likelihood``/``impact``/``relevance``. Only ``risk`` survives as a rename;
# v3 ``scope`` was blast radius, which v4 folds into ``impact``, so its value is
# discarded rather than carried into ``relevance`` (PR-goal fit). Remove this
# shim once no v3 producer output remains in flight.
DEFAULT_MIGRATED_RELEVANCE = 0.5
_MIGRATION_ID_PREVIEW = 10


class LegacyFloatMigration(NamedTuple):
    """Finding IDs touched by :func:`migrate_legacy_floats`."""

    migrated: list[str]
    relevance_defaulted: list[str]

    def __bool__(self) -> bool:
        return bool(self.migrated)

    def warnings(self, source: str) -> list[str]:
        """Deprecation lines to log, most severe last."""
        if not self.migrated:
            return []
        lines = [
            f"[deprecated] {source}: {len(self.migrated)} finding(s) carry "
            "schema-v3 severity floats; 'risk' renamed to 'likelihood' and "
            "'scope' dropped (blast radius now belongs in 'impact'): "
            + _preview_ids(self.migrated)
        ]
        if self.relevance_defaulted:
            lines.append(
                f"[deprecated] {source}: RE-RATE REQUIRED — 'relevance' defaulted "
                f"to {DEFAULT_MIGRATED_RELEVANCE} on "
                f"{len(self.relevance_defaulted)} finding(s). v3 'scope' was blast "
                "radius, not PR-goal fit, so it cannot be migrated; relevance "
                "drives merge_class, so an unrated value can defer a real defect: "
                + _preview_ids(self.relevance_defaulted)
            )
        return lines


def _preview_ids(ids: list[str]) -> str:
    """Comma-joined IDs, truncated so a large report cannot flood the log."""
    head = ", ".join(ids[:_MIGRATION_ID_PREVIEW])
    extra = len(ids) - _MIGRATION_ID_PREVIEW
    return f"{head} (+{extra} more)" if extra > 0 else head


def _iter_migratable_findings(data: Any) -> Iterator[dict[str, Any]]:
    """Yield finding dicts from a report envelope or a producer section array.

    Producer arrays may also hold bare findings that never got wrapped in a
    section (``consolidate_reports`` rescues those), so an entry without a
    nested ``findings`` list is treated as a finding itself.
    """
    sections = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, dict):
            continue
        nested = section.get("findings")
        if isinstance(nested, list):
            yield from (f for f in nested if isinstance(f, dict))
        else:
            yield section


def migrate_legacy_floats(data: Any) -> LegacyFloatMigration:
    """Rewrite schema-v3 severity floats onto their v4 names, in place.

    ``risk`` becomes ``likelihood`` unless the finding already carries one (the
    v4 name wins, so a half-migrated producer cannot smuggle a stale value
    past the schema's ``additionalProperties: false``). ``scope`` is discarded.
    A migrated finding with no ``relevance`` gets ``DEFAULT_MIGRATED_RELEVANCE``
    — "adjacent to the change", which classifies ``non_blocking`` and puts the
    finding in front of a human instead of auto-deferring it.
    """
    migrated: list[str] = []
    relevance_defaulted: list[str] = []
    for finding in _iter_migratable_findings(data):
        if "risk" not in finding and "scope" not in finding:
            continue
        legacy_risk = finding.pop("risk", None)
        finding.pop("scope", None)
        if "likelihood" not in finding and legacy_risk is not None:
            finding["likelihood"] = legacy_risk
        ident = str(finding.get("id") or finding.get("title") or "<unidentified>")
        migrated.append(ident)
        if "relevance" not in finding:
            finding["relevance"] = DEFAULT_MIGRATED_RELEVANCE
            relevance_defaulted.append(ident)
    return LegacyFloatMigration(migrated, relevance_defaulted)


def _iter_section_findings(
    sections: list[dict[str, Any]],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (category, finding) tuples from a list of finding sections."""
    for section in sections:
        cat = section.get("category", "code_quality")
        for finding in section.get("findings", []):
            yield cat, finding


def build_severity_stats(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Build severity_counts + severity_category_matrix from finding sections.

    Counts each finding by its effective severity (explicit integer, else
    derived from likelihood/impact, else INFO) and tallies a
    severity x category matrix. Mirrors ``consolidate_reports.compute_statistics``
    but operates purely on findings — no agent_stats / redundancy.
    """
    severity_counts: dict[str, int] = {label: 0 for label in SEV_ORDER}
    matrix_data: dict[str, dict[str, int]] = {
        label: {cat: 0 for cat in MATRIX_CATEGORIES} for label in SEV_ORDER
    }

    total = 0
    for cat, finding in _iter_section_findings(sections):
        sev_int = _effective_severity(finding)
        label = SEV_LABELS.get(sev_int, "INFO")
        severity_counts[label] = severity_counts.get(label, 0) + 1
        if label in matrix_data and cat in matrix_data[label]:
            matrix_data[label][cat] += 1
        total += 1

    matrix: list[dict[str, Any]] = []
    for label in SEV_ORDER:
        row: dict[str, Any] = {"severity": label}
        row_total = 0
        for cat in MATRIX_CATEGORIES:
            count = matrix_data[label].get(cat, 0)
            row[cat] = count
            row_total += count
        row["total"] = row_total
        matrix.append(row)

    return {
        "total_findings": total,
        "severity_counts": severity_counts,
        "severity_category_matrix": matrix,
    }


def build_merge_class_stats(findings: list[dict[str, Any]]) -> dict[str, int]:
    """Count classified findings, returning an empty dict when none are classified."""
    counts = {merge_class: 0 for merge_class in MERGE_CLASS_ORDER}
    classified = False
    for finding in findings:
        merge_class = finding.get("merge_class")
        if merge_class in counts:
            counts[merge_class] += 1
            classified = True
    return counts if classified else {}
