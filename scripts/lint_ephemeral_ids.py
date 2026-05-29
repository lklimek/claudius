#!/usr/bin/env python3
"""Dumb advisory lint for ephemeral review-finding IDs in committed artifacts.

Ephemeral IDs (e.g. CMT-001, SEC-014, RUST-123, CALL-005) are reassigned every
time the consolidator runs and become dead references after merge. They must
never appear in committed source code, comments, or docs.

Permanent IDs (ADR-NNN, RFC-NNN, CWE-NNN, CVE-YYYY-NNNN, OWASP-*, GHSA, GH
issue/PR refs, TODO/FIXME, committed test-spec IDs) are NOT flagged by this
lint — only the consolidator-owned prefix set is matched.

The prefix set is imported from ``consolidate_reports`` to make drift between
this lint and the consolidator structurally impossible. ``QA-`` is included as
a known code-quality language sub-prefix that the schema accepts; the rest
come straight from ``CATEGORY_PREFIX`` and ``CODE_QUALITY_PREFIXES``.

## Usage

    # File mode (default): scan every line of each file
    python3 lint_ephemeral_ids.py path/to/file.md path/to/another.py

    # Diff mode: read a unified diff from stdin (or `git diff $BASE...HEAD`)
    # and report only added (`+`) lines.
    git diff $BASE...HEAD | python3 lint_ephemeral_ids.py --diff

    # Text output for human eyeballing
    python3 lint_ephemeral_ids.py --format text path/to/file.md

The script ALWAYS exits 0 — this is advisory. Reviewer skills decide whether
each hit is a genuine violation or an in-skill example block that demonstrates
the rule. The intentional false positives in the lint's own docstrings and in
the skill files demonstrating this rule are by design: keep the lint dumb.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from consolidate_reports import CATEGORY_PREFIX, CODE_QUALITY_PREFIXES  # noqa: E402

# Build the prefix set from the consolidator's source of truth. Strip the
# trailing "-" so we can rebuild the regex on the alphabetic stems.
# ``QA-`` is added explicitly: the schema (review-report.schema.json) accepts
# it as a code-quality language sub-prefix even though the consolidator's
# Python dicts don't declare it. The drift test asserts this remains a
# SUPERSET of the consolidator's set.
_EXTRA_PREFIXES = {"QA-"}
PREFIXES: frozenset[str] = frozenset(
    set(CATEGORY_PREFIX.values()) | set(CODE_QUALITY_PREFIXES) | _EXTRA_PREFIXES
)
_STEMS = sorted(p.rstrip("-") for p in PREFIXES)
PATTERN = re.compile(r"\b(" + "|".join(_STEMS) + r")-\d{3}\b")


def scan_text(text: str, source: str, *, line_offset: int = 0) -> list[dict]:
    """Scan a block of text and return one hit per match.

    ``line_offset`` lets the caller shift reported line numbers when the text
    is a slice of a larger document (e.g. diff hunks). The default 0 means
    line numbers are 1-based relative to ``text``.
    """
    hits: list[dict] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for match in PATTERN.finditer(line):
            hits.append(
                {
                    "file": source,
                    "line": idx + line_offset,
                    "line_text": line.rstrip(),
                    "matched_id": match.group(0),
                }
            )
    return hits


def scan_file(path: Path) -> list[dict]:
    """Scan every line of a file and return hits."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"WARN: cannot read {path}: {e}", file=sys.stderr)
        return []
    return scan_text(text, str(path))


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")


def scan_diff(diff_text: str) -> list[dict]:
    """Scan a unified diff and report only added (`+`) lines.

    File names come from ``+++ b/<path>`` headers. Line numbers come from the
    hunk header's new-file start, incremented for each context (` `) and
    added (`+`) line; removed (`-`) lines do not advance the new-file pointer.
    Skips diff metadata lines (``---``, ``+++``, ``@@``, ``diff``, ``index``)
    and the ``\\ No newline at end of file`` marker (which is metadata, not
    content, and must not advance the new-file pointer).
    """
    hits: list[dict] = []
    current_file = "<stdin>"
    new_line = 0

    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            m = _FILE_HEADER.match(raw)
            if m:
                current_file = m.group(1)
            continue
        if (
            raw.startswith("--- ")
            or raw.startswith("diff ")
            or raw.startswith("index ")
        ):
            continue
        if raw.startswith("\\ "):
            # "\ No newline at end of file" — diff metadata, not content.
            continue
        m = _HUNK_HEADER.match(raw)
        if m:
            new_line = int(m.group(1))
            continue
        if raw.startswith("+"):
            content = raw[1:]
            for match in PATTERN.finditer(content):
                hits.append(
                    {
                        "file": current_file,
                        "line": new_line,
                        "line_text": content.rstrip(),
                        "matched_id": match.group(0),
                    }
                )
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return hits


def format_text(hits: list[dict]) -> str:
    """Render hits as one-line-per-hit human-readable text."""
    if not hits:
        return ""
    return "\n".join(
        f"{h['file']}:{h['line']}: {h['matched_id']}: {h['line_text']}" for h in hits
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dumb advisory lint for ephemeral review-finding IDs "
            "(CMT-/SEC-/RUST-/CALL-/etc.) in committed artifacts. "
            "Always exits 0; the reviewer dismisses in-skill example matches."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Files to scan (file mode). Ignored when --diff is set.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Read a unified diff from stdin and report only added (`+`) lines.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format (default: json).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hits: list[dict] = []

    if args.diff:
        diff_text = sys.stdin.read()
        hits = scan_diff(diff_text)
    else:
        for path in args.files:
            hits.extend(scan_file(path))

    if args.format == "json":
        json.dump(hits, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        text = format_text(hits)
        if text:
            print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
