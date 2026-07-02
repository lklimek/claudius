#!/usr/bin/env python3
"""Shared OWASP severity derivation and statistics helpers.

Single source of truth for the severity band table, the per-finding
severity derivation (mean of risk/impact/scope mapped to a CVSS-aligned
band), and the summary-statistics / category-matrix builder. Both the
coordinator (``consolidate_reports.py``) and the renderer
(``generate_review_report.py``) import from here so the math lives in
exactly one place.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any


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


# NOTE: scope-weighting/capping is a deliberate future consideration; the
# unweighted mean below is intentionally left unchanged here to avoid
# rebanding every existing report. The observed inflation is a mis-rating
# (scope defaulted to 1.0), addressed in the authoring skills and a
# non-blocking consistency gate, not in this formula.
def derive_overall(finding: dict[str, Any]) -> float | None:
    """Arithmetic mean of risk + impact + scope when all three are finite floats.

    Returns None when any dimension is absent, non-numeric, or non-finite
    (NaN/Infinity) — NaN would sink a CRITICAL finding to INFO and +Infinity
    would force it to CRITICAL regardless of the other two dimensions.
    """
    dims = []
    for key in ("risk", "impact", "scope"):
        value = finding.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        if math.isnan(value) or math.isinf(value):
            return None
        dims.append(float(value))
    return sum(dims) / 3.0


def derive_severity_int(overall: float) -> int:
    """Map an overall_severity float to the 1..5 integer severity band."""
    for threshold, level in _SEVERITY_BANDS:
        if overall >= threshold:
            return level
    return 1


def derive_finding_severity(finding: dict[str, Any]) -> int | None:
    """Return the integer band for a finding when risk/impact/scope are all present.

    Returns None when any of the three OWASP floats is absent or non-numeric,
    signalling the caller to fall back to an explicit ``severity`` (or INFO).
    """
    overall = derive_overall(finding)
    if overall is None:
        return None
    return derive_severity_int(overall)


def _effective_severity(finding: dict[str, Any]) -> int:
    """Resolve a finding's integer severity for counting.

    Prefers the band derived from the OWASP risk/impact/scope floats — per the
    severity skill's doctrine, the float trio is the single source of truth,
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
    derived from risk/impact/scope, else INFO) and tallies a
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
