#!/usr/bin/env python3
"""Validate a review report JSON file against the Claudius report schema.

Usage:
    python3 scripts/validate_report.py <report.json> [--schema <schema.json>]
        [--producer] [--strict-v4]

Schema-v3 files are migrated in memory and validated in that form; the verdict
says so, and --strict-v4 rejects them outright for callers that need v4 on disk.

Exit codes:
    0  Valid
    1  Validation error (schema mismatch, or schema-v3 input under --strict-v4)
    2  File/parse error (missing file, invalid JSON)
"""

import re
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from severity_util import (  # noqa: E402
    GATE_CITATION_RE,
    GATE_IDS,
    INFORMATIONAL_FLOOR_KEYS,
    derive_finding_severity,
    derive_severity_int,
    migrate_legacy_floats,
    reject_non_finite_constant,
    sanitize_log_value,
)

try:
    import jsonschema
except ImportError:
    print(
        "Error: python3-jsonschema is required. Install with: apt install python3-jsonschema",
        file=sys.stderr,
    )
    sys.exit(2)

DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
)

# Un-rated-axis check fires only on reports with enough findings to be
# meaningful, and only when a dimension is near-uniform — see check_consistency.
_AXIS_MIN_FINDINGS = 5
_AXIS_SHARE_THRESHOLD = 0.8
_RATED_AXES = ("likelihood", "impact", "relevance")

# Schema versions that define merge_class / intent_basis.
_MERGE_CLASS_SCHEMA_VERSIONS = ("3.2.0", "4.0.0")
_MERGE_CLASS_VERSIONS_TEXT = " or ".join(_MERGE_CLASS_SCHEMA_VERSIONS)


def _is_informational_floor(finding: dict) -> bool:
    """True when every severity float is exactly 0.0 — the Informational floor."""
    return all(finding.get(axis) == 0.0 for axis in INFORMATIONAL_FLOOR_KEYS)


def _fid(finding: dict) -> str:
    """Finding ID as a log-safe token.

    These warnings share a stream a coordinator parses, and they are emitted
    before any schema check has constrained ``id`` — an unsanitized newline
    lets a finding forge additional report lines.
    """
    return sanitize_log_value(finding.get("id") or "?")


def _iter_findings(report: dict) -> list[dict]:
    """Flatten all per-section findings into one list (empty on odd shapes).

    Mirrors ``severity_util._iter_migratable_findings``: a producer array may
    hold bare findings that were never wrapped in a section, so an entry with
    no nested ``findings`` list is treated as a finding itself. Dropping those
    silently would exempt them from the merge-class gate checks below — the one
    shape a producer is most likely to get wrong is then the one shape that
    skips validation.
    """
    sections = report.get("findings", []) if isinstance(report, dict) else report
    out: list[dict] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        nested = section.get("findings")
        if isinstance(nested, list):
            out.extend(f for f in nested if isinstance(f, dict))
        elif nested is None:
            out.append(section)
    return out


def check_producer_consistency(sections: list) -> list[str]:
    """Merge-classification warnings for a producer-stage section array.

    Producer mode skips the rest of ``check_consistency`` — most of it needs
    report-level context a producer has not built yet — but the gate rules do
    not, and the only producers allowed to author a ``blocking`` finding are
    validated exclusively in this mode. Skipping them here left every
    inline-authored gate citation unchecked.
    """
    warnings: list[str] = []
    for f in _iter_findings(sections):
        warnings.extend(check_merge_classification(f))
    return warnings


def check_merge_classification(f: dict) -> list[str]:
    """Gate-citation warnings for one finding's merge_class / intent_basis.

    The blocker gates in ``skills/severity/SKILL.md`` §2 are the change's
    headline control, and prose is all that enforced them: any non-empty
    ``intent_basis`` used to pass, so a bare requirement quote read as a cited
    gate. Both directions are checked, because both are silent failures:

    - ``blocking`` without a valid ``G-*:`` citation — the gate that stops the
      PR was never named, so nobody can check whether one was really tripped.
    - a valid citation on anything other than ``blocking`` — a gate-tripping
      finding parked as ``non_blocking`` or, worse, ``out_of_scope_follow_up``,
      which the doctrine reads as "acceptable to never fix". Nothing else in
      the pipeline can catch that one.

    Split out of :func:`check_consistency` so producer mode can run it: the
    three producers permitted to emit ``merge_class`` inline (review-pr Pass C,
    check-pr-comments, review-dependency) are validated with ``--producer``,
    which skips the rest of the gate.
    """
    warnings: list[str] = []
    merge_class = f.get("merge_class")
    ai_verdict = f.get("ai_verdict")
    if (
        ai_verdict in {"false_positive", "duplicate"}
        and merge_class is not None
        and merge_class != "disputed"
    ):
        warnings.append(
            f"[consistency] finding {_fid(f)}: ai_verdict={ai_verdict} "
            f"should use merge_class=disputed, not {merge_class}"
        )

    intent_basis = f.get("intent_basis")
    text = intent_basis.strip() if isinstance(intent_basis, str) else ""
    citation = GATE_CITATION_RE.match(text) if text else None
    gate = citation.group(1) if citation else None
    evidence = citation.group(2).strip() if citation else ""

    if merge_class == "blocking":
        if not text:
            warnings.append(
                f"[consistency] finding {_fid(f)}: merge_class=blocking "
                "requires a non-empty intent_basis"
            )
        elif gate is None:
            warnings.append(
                f"[consistency] finding {_fid(f)}: merge_class=blocking requires "
                "intent_basis to cite a blocker gate as 'G-ID: evidence' "
                f"(per claudius:severity §2), got {sanitize_log_value(text)!r}"
            )
        elif gate not in GATE_IDS:
            warnings.append(
                f"[consistency] finding {_fid(f)}: intent_basis cites unknown "
                f"gate {sanitize_log_value(gate)!r}; valid gates are "
                f"{', '.join(GATE_IDS)}"
            )
        elif not evidence:
            warnings.append(
                f"[consistency] finding {_fid(f)}: intent_basis cites {gate} "
                "with no evidence after the colon — name what trips the gate"
            )
    else:
        # The reverse rule asks a different question from the forward one, so it
        # must not reuse the anchored citation match. Forward asks "is this in
        # canonical 'G-ID: evidence' form?" and is rightly strict. Reverse asks
        # "does a gate appear here at all?" — and a deferral reading
        # "Trips G-SECRET: seed in log" escaped the anchor entirely, which is
        # precisely the silent deferral this check exists to catch. Scan.
        mentioned = gate if gate in GATE_IDS else _mentioned_gate(text)
        if mentioned:
            warnings.append(
                f"[consistency] finding {_fid(f)}: intent_basis cites "
                f"{mentioned} but merge_class={merge_class or 'absent'} — a "
                "tripped gate is merge_class=blocking; deferring one is a "
                "doctrine violation the human must be told about explicitly"
            )
    return warnings


def _mentioned_gate(text: str) -> str | None:
    """First known gate ID appearing anywhere in *text*, else None.

    Deliberately laxer than ``GATE_CITATION_RE``: this feeds the reverse rule,
    where a missed detection silently licenses the exact deferral the doctrine
    forbids, while a false positive merely asks a human to look. Word-bounded so
    ``G-DATA`` does not match inside a longer token.
    """
    for gate in GATE_IDS:
        if re.search(rf"\b{re.escape(gate)}\b", text):
            return gate
    return None


def check_consistency(report: dict) -> list[str]:
    """Return non-blocking ``[consistency]`` warnings for a schema-valid report.

    (i) Label/band mismatch — an explicit integer ``severity`` that disagrees
    with the band recomputed from the finding's likelihood/impact floats (and,
    separately, from an explicit ``overall_severity`` when present).
    (ii) Un-rated-axis smell — when one dimension (likelihood, impact, or
    relevance) holds an identical value across most findings, signalling it was
    defaulted rather than rated per finding. Informational-floor findings are
    excluded from the sample: their exact zeros are a mandated rating, not a
    default.
    (iii) Dismissed finding with a non-disputed merge classification.
    (iv) Blocking finding without the requirement or claim that makes it blocking.
    (v) Merge-classification fields — on findings, top_findings, or
    summary_statistics — used with a schema version predating them.

    Warnings are advisory: callers print them but never fail validation.
    """
    findings = _iter_findings(report)
    warnings: list[str] = []
    schema_version = report.get("schema_version")

    for f in findings:
        schema_fields = [
            field for field in ("merge_class", "intent_basis") if field in f
        ]
        if schema_fields and schema_version not in _MERGE_CLASS_SCHEMA_VERSIONS:
            warnings.append(
                f"[consistency] finding {_fid(f)}: merge-classification "
                f"fields ({', '.join(schema_fields)}) require schema_version "
                f"{_MERGE_CLASS_VERSIONS_TEXT}, not {schema_version}"
            )

        warnings.extend(check_merge_classification(f))

        sev = f.get("severity")
        has_sev = isinstance(sev, int) and not isinstance(sev, bool)
        if not has_sev:
            continue
        derived = derive_finding_severity(f)
        if derived is not None and sev != derived:
            warnings.append(
                f"[consistency] finding {_fid(f)}: explicit severity={sev} "
                f"disagrees with band {derived} computed from its floats "
                f"(likelihood={f.get('likelihood')}, impact={f.get('impact')}); "
                "labels are derived — re-rate the floats, do not hand-set severity"
            )
        overall = f.get("overall_severity")
        if isinstance(overall, (int, float)) and not isinstance(overall, bool):
            overall_band = derive_severity_int(float(overall))
            if sev != overall_band:
                warnings.append(
                    f"[consistency] finding {_fid(f)}: explicit severity={sev} "
                    f"disagrees with overall_severity={float(overall):.3f} (band {overall_band})"
                )

    # Merge-classification fields also appear outside per-section findings.
    report_level_fields: list[str] = []
    top_findings = report.get("top_findings")
    if isinstance(top_findings, list) and any(
        isinstance(tf, dict) and "merge_class" in tf for tf in top_findings
    ):
        report_level_fields.append("top_findings[].merge_class")
    summary_stats = report.get("summary_statistics")
    if isinstance(summary_stats, dict) and "merge_class_counts" in summary_stats:
        report_level_fields.append("summary_statistics.merge_class_counts")
    if report_level_fields and schema_version not in _MERGE_CLASS_SCHEMA_VERSIONS:
        warnings.append(
            "[consistency] report: merge-classification fields "
            f"({', '.join(report_level_fields)}) require schema_version "
            f"{_MERGE_CLASS_VERSIONS_TEXT}, not {schema_version}"
        )

    # Informational-floor findings are rated, not defaulted — their exact zeros
    # are mandated for praise, clean passes and RESOLVED comments. Counting them
    # makes a report that is mostly good news look mostly unrated, so they leave
    # the sample entirely rather than just the modal value.
    rated = [f for f in findings if not _is_informational_floor(f)]
    if len(rated) >= _AXIS_MIN_FINDINGS:
        for axis in _RATED_AXES:
            values = [
                f[axis]
                for f in rated
                if isinstance(f.get(axis), (int, float))
                and not isinstance(f.get(axis), bool)
            ]
            if not values:
                continue
            top_value, count = Counter(values).most_common(1)[0]
            if count / len(rated) >= _AXIS_SHARE_THRESHOLD:
                extra = (
                    " (relevance = fit to this PR's stated goal, per"
                    " claudius:severity — it decides merge_class)"
                    if axis == "relevance"
                    else ""
                )
                warnings.append(
                    f"[consistency] {count}/{len(rated)} rated findings have "
                    f"{axis}={top_value} — {axis} may be unrated; rate it per finding{extra}"
                )

    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate report JSON against schema.")
    parser.add_argument("report", help="Path to report JSON file")
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA),
        help="Path to JSON schema (default: schemas/review-report.schema.json)",
    )
    parser.add_argument(
        "--producer",
        "--section-array",
        action="store_true",
        help="Validate a producer-stage array of finding sections",
    )
    parser.add_argument(
        "--strict-v4",
        action="store_true",
        help="Fail (exit 1) when the file needs the schema-v3 migration to validate",
    )
    args = parser.parse_args()

    try:
        schema = json.loads(Path(args.schema).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Schema error: {e}", file=sys.stderr)
        return 2

    if args.producer:
        if not isinstance(schema, dict):
            print(
                "Schema error: schema root must be a JSON object",
                file=sys.stderr,
            )
            return 2
        definitions = schema.get("$defs")
        if (
            not isinstance(definitions, dict)
            or "finding_section_array" not in definitions
        ):
            print(
                "Schema error: missing $defs.finding_section_array",
                file=sys.stderr,
            )
            return 2
        schema = {
            "$schema": schema.get(
                "$schema", "https://json-schema.org/draft/2020-12/schema"
            ),
            "$defs": definitions,
            "$ref": "#/$defs/finding_section_array",
        }

    try:
        report = json.loads(
            Path(args.report).read_text(), parse_constant=reject_non_finite_constant
        )
    except FileNotFoundError:
        print(f"Report not found: {args.report}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"Invalid JSON in {args.report}: {e}", file=sys.stderr)
        return 2

    # Validate the migrated shape: in-flight schema-v3 reports are accepted on
    # read, but only the v4 float names are ever considered valid.
    migration = migrate_legacy_floats(report)
    for warning in migration.warnings(args.report):
        print(warning, file=sys.stderr)

    if migration and args.strict_v4:
        print(
            f"Validation failed: {args.report} is schema-v3 on disk and only "
            "validates after in-memory migration (--strict-v4)",
            file=sys.stderr,
        )
        return 1

    validator_cls = jsonschema.validators.validator_for(schema)
    # Enable format validation (e.g., "uri", "date", "date-time") so that
    # format keywords are enforced, not just treated as annotations.
    try:
        checker = jsonschema.FormatChecker()
    except Exception:
        checker = None
    validator = validator_cls(schema, format_checker=checker)
    errors = sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path))

    if not errors:
        # Consistency gate: advisory only — never changes the exit code.
        checks = (
            check_producer_consistency(report)
            if args.producer
            else check_consistency(report)
        )
        for warning in checks:
            print(warning, file=sys.stderr)
        # Never certify the on-disk bytes when only the migrated copy passed:
        # the file itself still carries v3 float names the v4 schema rejects.
        if migration:
            print(
                f"Valid (after schema-v3 migration; on-disk file is v3): {args.report}"
            )
        else:
            print(f"Valid: {args.report}")
        return 0

    print(
        f"Validation failed: {len(errors)} error(s) in {args.report}", file=sys.stderr
    )
    for i, error in enumerate(errors, 1):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        print(f"  {i}. [{path}] {error.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
