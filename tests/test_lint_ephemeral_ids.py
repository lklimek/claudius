"""Tests for scripts/lint_ephemeral_ids.py.

Covers:
- Positive matches across every consolidator prefix.
- Negative cases for the documented allow-list (ADR/RFC/CWE/CVE/OWASP/GHSA/etc.).
- Word-boundary edge cases (5-digit suffix rejected, no-boundary prefix rejected).
- ``--diff`` parsing (only added lines, line numbers from hunk headers).
- Prefix-source-of-truth assertion: lint's PREFIXES is a superset of the
  consolidator's CATEGORY_PREFIX values.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lint_ephemeral_ids.py"

# Make the script importable for direct API tests.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import lint_ephemeral_ids as lint  # noqa: E402
from consolidate_reports import CATEGORY_PREFIX  # noqa: E402


# ---------------------------------------------------------------------------
# Positive cases — every consolidator-owned prefix
# ---------------------------------------------------------------------------
POSITIVE_CASES = [
    "CMT-001",
    "SEC-014",
    "RUST-123",
    "CALL-005",
    "PPM-002",
    "DEP-007",
    "CODE-099",
    "QA-100",
    "PROJ-001",
    "PY-042",
    "GO-007",
    "FE-111",
    "DOC-002",
]


@pytest.mark.parametrize("token", POSITIVE_CASES)
def test_positive_match(token: str) -> None:
    hits = lint.scan_text(f"prefix {token} suffix", "<test>")
    assert len(hits) == 1
    assert hits[0]["matched_id"] == token


# ---------------------------------------------------------------------------
# Negative cases — documented allow-list
# ---------------------------------------------------------------------------
NEGATIVE_CASES = [
    "ADR-007",
    "RFC-2119",
    "CWE-79",
    "CVE-2024-1234",
    "OWASP-A02",
    "OWASP-LLM01",
    "OWASP-API03",
    "GHSA-abc1-def2-ghi3",
    "#1234",
    "org/repo#42",
    "TODO",
    "FIXME",
    "XXX",
    "HACK",
    "TS-001",  # test-spec, not in consolidator set
    "T-1234",  # too short prefix
]


@pytest.mark.parametrize("token", NEGATIVE_CASES)
def test_negative_no_match(token: str) -> None:
    hits = lint.scan_text(f"prefix {token} suffix", "<test>")
    assert hits == []


# ---------------------------------------------------------------------------
# Word-boundary edges
# ---------------------------------------------------------------------------
def test_five_digit_suffix_rejected() -> None:
    """Regex requires exactly 3 digits — 5-digit IDs are NOT ephemeral."""
    hits = lint.scan_text("see RUST-12345 docs", "<test>")
    assert hits == []


def test_no_left_word_boundary_rejected() -> None:
    """XRUST-001 must NOT match — the X eats the left \\b."""
    hits = lint.scan_text("token XRUST-001 here", "<test>")
    assert hits == []


def test_trailing_punctuation_still_matches() -> None:
    hits = lint.scan_text("see CMT-001. and done", "<test>")
    assert len(hits) == 1
    assert hits[0]["matched_id"] == "CMT-001"


def test_multiple_matches_same_line() -> None:
    hits = lint.scan_text("both CMT-001 and SEC-014 here", "<test>")
    matched = {h["matched_id"] for h in hits}
    assert matched == {"CMT-001", "SEC-014"}
    assert all(h["line"] == 1 for h in hits)


# ---------------------------------------------------------------------------
# Diff mode
# ---------------------------------------------------------------------------
DIFF_FIXTURE = """\
diff --git a/foo.py b/foo.py
index 1234567..89abcde 100644
--- a/foo.py
+++ b/foo.py
@@ -10,4 +10,5 @@
 context line CMT-001 should be ignored
-removed line SEC-099 should be ignored
+added line CMT-002 should match
+another added RUST-007
 final context line
"""


def test_diff_mode_only_added_lines() -> None:
    hits = lint.scan_diff(DIFF_FIXTURE)
    matched_ids = sorted(h["matched_id"] for h in hits)
    assert matched_ids == ["CMT-002", "RUST-007"]
    files = {h["file"] for h in hits}
    assert files == {"foo.py"}


def test_diff_mode_line_numbers_from_hunk() -> None:
    """Added lines should report line numbers offset from hunk header start."""
    hits = lint.scan_diff(DIFF_FIXTURE)
    by_id = {h["matched_id"]: h["line"] for h in hits}
    # Hunk starts at new-file line 10; one context (10), one removed (skipped),
    # then two added lines at 11 and 12.
    assert by_id["CMT-002"] == 11
    assert by_id["RUST-007"] == 12


def test_diff_mode_via_subprocess_stdin() -> None:
    """End-to-end: pipe a diff through stdin, parse JSON output."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--diff"],
        input=DIFF_FIXTURE,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    matched = sorted(h["matched_id"] for h in payload)
    assert matched == ["CMT-002", "RUST-007"]


# ---------------------------------------------------------------------------
# File mode end-to-end
# ---------------------------------------------------------------------------
def test_file_mode_via_subprocess(tmp_path: Path) -> None:
    target = tmp_path / "sample.md"
    target.write_text("Talk about CMT-001 here.\nNo hits on this line.\nAlso SEC-014.\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    by_line = {h["line"]: h["matched_id"] for h in payload}
    assert by_line == {1: "CMT-001", 3: "SEC-014"}


def test_text_format_output(tmp_path: Path) -> None:
    target = tmp_path / "sample.md"
    target.write_text("Hit CMT-001 here.\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "text", str(target)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    assert "CMT-001" in result.stdout
    assert str(target) in result.stdout


def test_empty_files_list_emits_empty_json() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_always_exit_zero(tmp_path: Path) -> None:
    """Even when hits are found, exit code is 0 (advisory lint)."""
    target = tmp_path / "loud.md"
    target.write_text("CMT-001 SEC-014 RUST-123\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Source-of-truth assertion: lint PREFIXES must cover the consolidator set.
# ---------------------------------------------------------------------------
def test_prefixes_superset_of_consolidator() -> None:
    """Drift between lint and consolidator must be structurally impossible."""
    consolidator_set = set(CATEGORY_PREFIX.values())
    assert consolidator_set.issubset(set(lint.PREFIXES)), (
        f"Lint missing prefixes from consolidator: "
        f"{consolidator_set - set(lint.PREFIXES)}"
    )


def test_pattern_built_from_prefixes() -> None:
    """Regex must reflect the imported prefix set, not a stale literal."""
    # Every prefix stem (without the dash) must appear in the compiled pattern.
    for prefix in lint.PREFIXES:
        stem = prefix.rstrip("-")
        assert stem in lint.PATTERN.pattern, f"Stem {stem!r} missing from regex"
