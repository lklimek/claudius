#!/usr/bin/env python3
"""Validate a review report JSON file against the Claudius report schema.

Usage:
    python3 scripts/validate_report.py <report.json> [--schema <schema.json>]

Exit codes:
    0  Valid
    1  Validation error (schema mismatch)
    2  File/parse error (missing file, invalid JSON)
"""

import argparse
import json
import sys
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate report JSON against schema.")
    parser.add_argument("report", help="Path to report JSON file")
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA),
        help="Path to JSON schema (default: schemas/review-report.schema.json)",
    )
    args = parser.parse_args()

    try:
        schema = json.loads(Path(args.schema).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Schema error: {e}", file=sys.stderr)
        return 2

    try:
        report = json.loads(Path(args.report).read_text())
    except FileNotFoundError:
        print(f"Report not found: {args.report}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
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
