#!/usr/bin/env python3
"""Validate a review report JSON file against the Claudius report schema.

Usage:
    python3 scripts/validate_report.py <report.json> [--schema <schema.json>]
        [--producer]

Exit codes:
    0  Valid
    1  Validation error (schema mismatch)
    2  File/parse error (missing file, invalid JSON)
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from severity_util import (  # noqa: E402
    derive_finding_severity,
    derive_severity_int,
    reject_non_finite_constant,
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


def _iter_findings(report: dict) -> list[dict]:
    """Flatten all per-section findings into one list (empty on odd shapes)."""
    out: list[dict] = []
    for section in report.get("findings", []) or []:
        if isinstance(section, dict):
            out.extend(
                f for f in section.get("findings", []) or [] if isinstance(f, dict)
            )
    return out


def check_consistency(report: dict) -> list[str]:
    """Return non-blocking ``[consistency]`` warnings for a schema-valid report.

    (i) Label/band mismatch — an explicit integer ``severity`` that disagrees
    with the band recomputed from the finding's risk/impact/scope floats (and,
    separately, from an explicit ``overall_severity`` when present).
    (ii) Un-rated-axis smell — when one dimension (risk, impact, or scope) holds
    an identical value across most findings, signalling it was defaulted rather
    than rated per finding.
    (iii) Dismissed finding with a non-disputed merge classification.
    (iv) Blocking finding without the requirement or claim that makes it blocking.
    (v) Merge-classification fields — on findings, top_findings, or
    summary_statistics — used with a pre-3.2.0 schema version.

    Warnings are advisory: callers print them but never fail validation.
    """
    findings = _iter_findings(report)
    warnings: list[str] = []
    schema_version = report.get("schema_version")

    for f in findings:
        schema_fields = [
            field for field in ("merge_class", "intent_basis") if field in f
        ]
        if schema_fields and schema_version != "3.2.0":
            warnings.append(
                f"[consistency] finding {f.get('id', '?')}: 3.2.0-only fields "
                f"({', '.join(schema_fields)}) require schema_version=3.2.0, "
                f"not {schema_version}"
            )

        merge_class = f.get("merge_class")
        ai_verdict = f.get("ai_verdict")
        if (
            ai_verdict in {"false_positive", "duplicate"}
            and merge_class is not None
            and merge_class != "disputed"
        ):
            warnings.append(
                f"[consistency] finding {f.get('id', '?')}: ai_verdict={ai_verdict} "
                f"should use merge_class=disputed, not {merge_class}"
            )
        intent_basis = f.get("intent_basis")
        if merge_class == "blocking" and (
            not isinstance(intent_basis, str) or not intent_basis.strip()
        ):
            warnings.append(
                f"[consistency] finding {f.get('id', '?')}: merge_class=blocking "
                "requires a non-empty intent_basis"
            )

        sev = f.get("severity")
        has_sev = isinstance(sev, int) and not isinstance(sev, bool)
        if not has_sev:
            continue
        derived = derive_finding_severity(f)
        if derived is not None and sev != derived:
            warnings.append(
                f"[consistency] finding {f.get('id', '?')}: explicit severity={sev} "
                f"disagrees with band {derived} computed from its floats "
                f"(risk={f.get('risk')}, impact={f.get('impact')}, scope={f.get('scope')}); "
                "labels are derived — re-rate the floats, do not hand-set severity"
            )
        overall = f.get("overall_severity")
        if isinstance(overall, (int, float)) and not isinstance(overall, bool):
            overall_band = derive_severity_int(float(overall))
            if sev != overall_band:
                warnings.append(
                    f"[consistency] finding {f.get('id', '?')}: explicit severity={sev} "
                    f"disagrees with overall_severity={float(overall):.3f} (band {overall_band})"
                )

    # 3.2.0-only additions can also appear outside per-section findings.
    report_level_fields: list[str] = []
    top_findings = report.get("top_findings")
    if isinstance(top_findings, list) and any(
        isinstance(tf, dict) and "merge_class" in tf for tf in top_findings
    ):
        report_level_fields.append("top_findings[].merge_class")
    summary_stats = report.get("summary_statistics")
    if isinstance(summary_stats, dict) and "merge_class_counts" in summary_stats:
        report_level_fields.append("summary_statistics.merge_class_counts")
    if report_level_fields and schema_version != "3.2.0":
        warnings.append(
            "[consistency] report: 3.2.0-only fields "
            f"({', '.join(report_level_fields)}) require schema_version=3.2.0, "
            f"not {schema_version}"
        )

    if len(findings) >= _AXIS_MIN_FINDINGS:
        for axis in ("risk", "impact", "scope"):
            values = [
                f[axis]
                for f in findings
                if isinstance(f.get(axis), (int, float))
                and not isinstance(f.get(axis), bool)
            ]
            if not values:
                continue
            top_value, count = Counter(values).most_common(1)[0]
            if count / len(findings) >= _AXIS_SHARE_THRESHOLD:
                extra = (
                    " (scope = real blast radius, per claudius:severity)"
                    if axis == "scope"
                    else ""
                )
                warnings.append(
                    f"[consistency] {count}/{len(findings)} findings have "
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
        if not args.producer:
            for warning in check_consistency(report):
                print(warning, file=sys.stderr)
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
