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
import re
from collections.abc import Iterator
from typing import Any, NamedTuple


def reject_non_finite_constant(constant: str) -> Any:
    """json ``parse_constant`` callback: reject bare NaN/Infinity/-Infinity.

    Python's ``json`` module decodes these non-finite literals by default. They
    slip past ``isinstance(x, float)`` and range checks (``nan >= t`` is always
    False; ``jsonschema`` min/max treats NaN as valid), silently corrupting
    severity math. Wiring this into every report-loading ``json.loads`` rejects
    them at parse time with a clear error instead.

    Bare literals only: an overflowing numeric such as ``1e400`` is a normal
    JSON number that Python converts to ``inf`` without consulting this
    callback. ``derive_overall``'s ``isinf`` check and the schema's
    ``maximum: 1.0`` are what stop that one.
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

# Blocker gates — the must-not-ship conditions that force merge_class=blocking.
# Source of truth is skills/severity/SKILL.md §2; this tuple mirrors it so the
# pipeline can enforce what the doctrine only states, and
# tests/test_gate_vocabulary.py parses that table to fail loudly when a gate is
# added to one and not the other.
GATE_IDS: tuple[str, ...] = (
    "G-INTENT",
    "G-DATA",
    "G-FUNDS",
    "G-CRYPTO",
    "G-SECRET",
    "G-UI-BROKEN",
    "G-UI-TEXT",
    "G-WYSIWYS",
    "G-AMOUNT",
    "G-DOUBLE",
    "G-PHISH",
    "G-BRICK",
    "G-SILENT",
    "G-PRIVACY",
    "G-GROWTH",
    "G-DEFAULTS",
)

# An intent_basis citing a gate: the ID, a colon, then the evidence for it.
GATE_CITATION_RE = re.compile(r"^\s*(G-[A-Z-]+)\s*:(.*)$", re.DOTALL)

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

# Band table, applied descending. Thresholds were originally derived from CVSS
# v4.0 bands; they are now specified by skills/severity/SKILL.md, which owns
# them outright and defers to no external methodology.
_SEVERITY_BANDS: list[tuple[float, int]] = [
    (0.9, 5),
    (0.7, 4),
    (0.4, 3),
    (0.1, 2),
]
_SEVERITY_EPSILON = 1e-9


def _is_number(value: Any) -> bool:
    """True for a real numeric scalar — bools are ints in Python, exclude them."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
    caller to resolve severity some other way — see :func:`_effective_severity`,
    which then prefers the highest surviving dimension or an explicit
    ``severity`` over falling through to INFO.
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
    ``consolidate_reports.py``). When the floats cannot derive a mean, takes
    the HIGHEST of the surviving dimension's band and any explicit integer,
    and only then falls through to 1 (INFO) — INFO means "no action required",
    so reaching it by accident is the failure this tool must not make.
    """
    derived = derive_finding_severity(finding)
    if derived is not None:
        return derived
    candidates: list[int] = []
    partial = _partial_dimension_band(finding)
    if partial is not None:
        candidates.append(partial)
    sev = finding.get("severity")
    if isinstance(sev, int) and not isinstance(sev, bool) and 1 <= sev <= 5:
        candidates.append(sev)
    return max(candidates) if candidates else 1


def _partial_dimension_band(finding: dict[str, Any]) -> int | None:
    """Band of the highest usable severity dimension, or None if there are none.

    Reached only when the floats are too damaged to derive a mean. Falling
    straight through to INFO there would resolve a half-rated finding to the
    one band meaning "no action required" — the wrong direction for a tool
    whose damaging failure is under-reporting. A `likelihood 1.0` with a
    missing `impact` is unrated, not harmless, so the surviving dimension sets
    the floor and a human sees it.
    """
    usable = [
        float(finding[key])
        for key in _SEVERITY_DIMENSIONS
        if _is_number(finding.get(key))
        and not math.isnan(finding[key])
        and not math.isinf(finding[key])
    ]
    return derive_severity_int(max(usable)) if usable else None


# ---------------------------------------------------------------------------
# Schema-v3 float migration (deprecated read path)
# ---------------------------------------------------------------------------
# v3 findings carried ``risk``/``impact``/``scope``. v4 carries
# ``likelihood``/``impact``/``relevance``. Only ``risk`` survives as a rename;
# v3 ``scope`` was blast radius, which v4 expects folded into ``impact``, so its
# value is discarded rather than carried into ``relevance`` (PR-goal fit).
# Remove this shim once no v3 producer output remains in flight.
DEFAULT_MIGRATED_RELEVANCE = 0.5
# Exact zeros on every axis: the Informational floor, the only rating whose
# meaning is "no defect here" (skills/severity/SKILL.md § Informational floor).
INFORMATIONAL_FLOOR_KEYS: tuple[str, ...] = ("likelihood", "impact", "relevance")
_MIGRATION_ID_PREVIEW = 10
_LOG_VALUE_MAX = 120
_LOG_UNSAFE_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_log_value(value: Any, limit: int = _LOG_VALUE_MAX) -> str:
    """Flatten producer-controlled text to one bounded, single-line token.

    Finding ``id``/``title`` reach log lines that a coordinator parses, and
    migration runs before schema validation, so the values are unconstrained at
    this point. Control characters — newlines above all — let a hostile finding
    forge whole log records (``Valid: report.json``); they collapse to spaces
    and the result is length-capped, so one finding can neither spoof a record
    nor flood the stream.
    """
    text = "" if value is None else value if isinstance(value, str) else str(value)
    # Space, not deletion: removing the separator runs neighbouring words
    # together and mangles the very text an operator is trying to read.
    text = " ".join(_LOG_UNSAFE_RE.sub(" ", text).split())
    if not text:
        return "<unidentified>"
    return text if len(text) <= limit else text[:limit] + "…"


class LegacyFloatMigration(NamedTuple):
    """Finding IDs touched by :func:`migrate_legacy_floats`."""

    migrated: list[str]
    relevance_defaulted: list[str]
    collisions: list[str]
    floored: list[str]
    likelihood_missing: list[str]

    def __bool__(self) -> bool:
        return bool(self.migrated)

    def warnings(self, source: str) -> list[str]:
        """Deprecation lines to log, most severe last."""
        if not self.migrated:
            return []
        source = sanitize_log_value(source)
        lines = [
            f"[deprecated] {source}: {len(self.migrated)} finding(s) carry "
            "schema-v3 severity floats; 'risk' renamed to 'likelihood', 'scope' "
            "dropped, and any severity/overall_severity computed under the v3 "
            "formula recomputed: " + _preview_ids(self.migrated)
        ]
        if self.floored:
            lines.append(
                f"[deprecated] {source}: {len(self.floored)} finding(s) matched the "
                "v3 informational convention (scope 0.0 with negligible risk and "
                "impact) and were set to the Informational floor of exact zeros; "
                "carrying their old floats forward would have promoted settled "
                "work to LOW and filed it as open: " + _preview_ids(self.floored)
            )
        if self.likelihood_missing:
            lines.append(
                f"[deprecated] {source}: {len(self.likelihood_missing)} finding(s) "
                "ended migration with no usable 'likelihood' — a legacy key was "
                "dropped and nothing replaced it, so their severity cannot be "
                "derived and is resolved from whatever dimension survives: "
                + _preview_ids(self.likelihood_missing)
            )
        if self.collisions:
            lines.append(
                f"[deprecated] {source}: both v3 and v4 float names present on "
                f"{len(self.collisions)} finding(s) — kept the HIGHER of "
                "'risk'/'likelihood' (one quantity, so a half-migrated producer "
                "must not silently downgrade itself) and the producer's own "
                "'relevance' over 'scope' (different quantities: a blast radius "
                "must not decide merge_class): " + _preview_ids(self.collisions)
            )
        defaulted = (
            f" 'relevance' was defaulted to {DEFAULT_MIGRATED_RELEVANCE} on "
            f"{len(self.relevance_defaulted)} of them (v3 'scope' is blast radius, "
            "not PR-goal fit, so it cannot be migrated) and drives merge_class."
            if self.relevance_defaulted
            else ""
        )
        lines.append(
            f"[deprecated] {source}: RE-RATE REQUIRED on {len(self.migrated)} "
            "finding(s). 'impact' is left exactly as the v3 producer rated it, and "
            "v3 rated impact EXCLUDING blast radius (which it carried separately "
            "in 'scope'), so wide-reaching findings are under-rated until a human "
            f"or validate-findings re-rates them.{defaulted} "
            + _preview_ids(self.migrated)
        )
        return lines


def _preview_ids(ids: list[str]) -> str:
    """Comma-joined IDs, truncated so a large report cannot flood the log."""
    head = ", ".join(ids[:_MIGRATION_ID_PREVIEW])
    extra = len(ids) - _MIGRATION_ID_PREVIEW
    return f"{head} (+{extra} more)" if extra > 0 else head


# The two float pairs collide for different reasons and resolve by different
# rules — they are separate functions so the distinction cannot be flattened
# back into one policy by a later edit.


def _merge_same_quantity(finding: dict[str, Any], legacy: str, current: str) -> bool:
    """Collapse ``risk``/``likelihood`` onto *current*, keeping the HIGHER value.

    Both names measure the same quantity, so a producer carrying both is
    half-migrated and disagreeing with itself. Preferring either name
    unconditionally can downgrade — ``risk 1.0`` with ``likelihood 0.1`` reads
    as MEDIUM from a CRITICAL — and this pair does feed the severity mean, so
    erring upward is the fail-safe direction. Returns True on a real conflict.
    """
    if legacy not in finding:
        return False
    legacy_value = finding.pop(legacy)
    if current not in finding:
        if legacy_value is not None:
            finding[current] = legacy_value
        return False
    current_value = finding[current]
    if not (_is_number(legacy_value) and _is_number(current_value)):
        return False
    if legacy_value == current_value:
        return False
    finding[current] = max(legacy_value, current_value)
    return True


def _discard_legacy_axis(finding: dict[str, Any], legacy: str, current: str) -> bool:
    """Drop ``scope`` outright; the producer's ``relevance`` is authoritative.

    These names measure different things — ``scope`` was blast radius, which v4
    folds into ``impact``, while ``relevance`` is fit to the PR's goal. Taking
    the higher would import a blast radius into the field that decides
    ``merge_class``, which is the defect this migration exists to avoid. A
    producer that supplied ``relevance`` has actually rated PR-fit, so its
    value wins however low it is.

    Keeping the lower value cannot under-report: ``relevance`` is not in the
    severity mean, so it cannot sink a band — the fail-safe argument for
    :func:`_merge_same_quantity` does not transfer. Returns True when a
    ``scope`` value was overridden rather than merely dropped.
    """
    if legacy not in finding:
        return False
    legacy_value = finding.pop(legacy)
    return current in finding and _is_number(legacy_value)


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


def _is_v3_informational(finding: dict[str, Any]) -> bool:
    """True for the pre-v4 informational convention: ``risk = impact = 0.1,
    scope = 0.0``, used for praise, verified-clean passes and RESOLVED comments.

    Those trios derived to 0.067 (INFO) under the three-term mean and derive to
    0.1 (LOW) under the two-term one, so a straight rename refiles every settled
    comment in an in-flight report as open LOW work. The band ceiling is what
    makes the heuristic safe: anything matching already derived to INFO in v3,
    so it cannot demote a finding that was ever above INFO.

    Only pure-v3 findings qualify; a half-migrated one carrying a v4 name is
    ambiguous and goes through the ordinary collision path instead.
    """
    if "likelihood" in finding or "relevance" in finding:
        return False
    values = {key: finding.get(key) for key in ("risk", "impact", "scope")}
    if not all(_is_number(value) for value in values.values()):
        return False
    return values["scope"] == 0.0 and max(values["risk"], values["impact"]) <= 0.1


def migrate_legacy_floats(data: Any) -> LegacyFloatMigration:
    """Rewrite schema-v3 severity floats onto their v4 names, in place.

    ``risk`` becomes ``likelihood``, taking the higher value when both names
    are present (:func:`_merge_same_quantity`).

    ``scope`` is always dropped and never contributes its value to
    ``relevance``, which resolves by exactly three cases: a producer-supplied
    ``relevance`` is kept unchanged however low; a finding matching the v3
    informational convention takes the Informational floor of exact zeros
    (:func:`_is_v3_informational`); anything else gets
    ``DEFAULT_MIGRATED_RELEVANCE`` ("adjacent to the change"), which classifies
    ``non_blocking`` so the finding reaches a human rather than being
    auto-deferred.

    Any ``severity``/``overall_severity`` on a migrated finding was computed
    under the v3 three-term mean, so it is recomputed from the v4 floats —
    dropped outright when they no longer support a band. Leaving the old label
    in place is the laundering this migration exists to prevent: renderers and
    ``cmd_regenerate`` trust a present label and would report the stale,
    lower band.

    Findings matching the v3 informational convention take the Informational
    floor instead — see :func:`_is_v3_informational`.
    """
    migrated: list[str] = []
    relevance_defaulted: list[str] = []
    collisions: list[str] = []
    floored: list[str] = []
    likelihood_missing: list[str] = []
    for finding in _iter_migratable_findings(data):
        if "risk" not in finding and "scope" not in finding:
            continue
        ident = sanitize_log_value(finding.get("id") or finding.get("title"))
        migrated.append(ident)

        if _is_v3_informational(finding):
            for key in ("risk", "scope"):
                finding.pop(key, None)
            finding.update(dict.fromkeys(INFORMATIONAL_FLOOR_KEYS, 0.0))
            floored.append(ident)
        else:
            conflict = _merge_same_quantity(finding, "risk", "likelihood")
            conflict |= _discard_legacy_axis(finding, "scope", "relevance")
            if conflict:
                collisions.append(ident)
            if "relevance" not in finding:
                finding["relevance"] = DEFAULT_MIGRATED_RELEVANCE
                relevance_defaulted.append(ident)
            if not _is_number(finding.get("likelihood")):
                likelihood_missing.append(ident)

        overall = derive_overall(finding)
        if overall is None:
            finding.pop("overall_severity", None)
            finding.pop("severity", None)
        else:
            finding["overall_severity"] = overall
            finding["severity"] = derive_severity_int(overall)
    return LegacyFloatMigration(
        migrated, relevance_defaulted, collisions, floored, likelihood_missing
    )


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

    Counts each finding by its effective severity — the band derived from
    likelihood/impact, else an explicit integer ``severity``, else INFO; see
    ``_effective_severity`` for why the derived band wins — and tallies a
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
