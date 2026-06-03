"""Regression tests for the producer-side permalink template documented in
``skills/check-pr-comments/SKILL.md``.

The ``check-pr-comments`` skill instructs producers to build
``location_permalink`` directly from ``metadata.project`` + ``metadata.commit``
+ ``location``. This module pins the URL form so a future SKILL edit can't
silently drift away from the canonical layout used by the coordinator.

The shape under test is a producer string template, not a Python helper, so
each test reconstructs the URL the way a producer LLM is told to (split
``project`` on ``/``, append ``/blob/<sha>/<path>``, then a line anchor
``#L<n>`` or ``#L<a>-L<b>``). The result is then cross-checked against
``consolidate_reports._build_permalink`` so producer output and coordinator
output agree byte-for-byte when both code paths see the same inputs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote as _url_quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr


def _producer_permalink(
    project: str | None,
    commit: str | None,
    location: str | None,
) -> str | None:
    """Reference implementation of the producer-side template documented in
    ``skills/check-pr-comments/SKILL.md``. Returns the URL or ``None`` when
    any required input is missing or unparseable — matching the SKILL's
    "omit, do not emit empty string" rule.
    """
    if not project or "/" not in project or not commit or not location:
        return None
    owner, _, repo = project.partition("/")
    if not owner or not repo:
        return None
    # Parse location: "path:line" or "path:start-end". Path-only is rejected
    # to match the coordinator (`consolidate_reports.parse_location`).
    if ":" not in location:
        return None
    path, _, lines = location.rpartition(":")
    if "-" in lines:
        start, _, end = lines.partition("-")
        # Both ends MUST be integers when `-` is present; reject malformed
        # forms like "file:1-" or "file:-2" that the coordinator regex rejects.
        if not start or not end:
            return None
        try:
            start_n = int(start)
            end_n = int(end)
        except ValueError:
            return None
    else:
        try:
            start_n = int(lines)
        except ValueError:
            return None
        end_n = None
    if not path:
        return None
    safe_path = _url_quote(path, safe="/")
    if end_n is None or end_n == start_n:
        anchor = f"#L{start_n}"
    else:
        anchor = f"#L{start_n}-L{end_n}"
    return f"https://github.com/{owner}/{repo}/blob/{commit}/{safe_path}{anchor}"


SHA = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Single-line and range anchors
# ---------------------------------------------------------------------------
class TestAnchorForm:
    def test_single_line(self):
        url = _producer_permalink("octo/widgets", SHA, "src/auth.rs:42")
        assert url == f"https://github.com/octo/widgets/blob/{SHA}/src/auth.rs#L42"

    def test_range(self):
        url = _producer_permalink(
            "dashpay/platform",
            SHA,
            "packages/rs-platform-wallet/src/wallet/transfer.rs:414-420",
        )
        assert url == (
            f"https://github.com/dashpay/platform/blob/{SHA}/"
            "packages/rs-platform-wallet/src/wallet/transfer.rs#L414-L420"
        )

    def test_collapsed_range_uses_single_anchor(self):
        # A `:42-42` range collapses to `#L42` to match the coordinator form.
        url = _producer_permalink("octo/widgets", SHA, "src/auth.rs:42-42")
        assert url == f"https://github.com/octo/widgets/blob/{SHA}/src/auth.rs#L42"


# ---------------------------------------------------------------------------
# Owner/repo extraction from metadata.project
# ---------------------------------------------------------------------------
class TestProjectSplit:
    def test_owner_repo_split(self):
        url = _producer_permalink("dashpay/platform", SHA, "f.rs:1")
        assert url is not None
        assert "/dashpay/platform/blob/" in url

    def test_missing_slash_returns_none(self):
        # A bare project name (no `/`) can't yield owner+repo.
        assert _producer_permalink("dashpay-only", SHA, "f.rs:1") is None

    def test_empty_owner_returns_none(self):
        assert _producer_permalink("/repo", SHA, "f.rs:1") is None

    def test_empty_repo_returns_none(self):
        assert _producer_permalink("owner/", SHA, "f.rs:1") is None


# ---------------------------------------------------------------------------
# Missing-input handling
# ---------------------------------------------------------------------------
class TestMissingInputs:
    def test_no_project(self):
        assert _producer_permalink(None, SHA, "f.rs:1") is None

    def test_no_commit(self):
        assert _producer_permalink("octo/widgets", None, "f.rs:1") is None

    def test_no_location(self):
        assert _producer_permalink("octo/widgets", SHA, None) is None

    def test_unparseable_line_number(self):
        assert _producer_permalink("octo/widgets", SHA, "f.rs:notanumber") is None

    def test_path_only_returns_none(self):
        # Path-only locations have no `:line` suffix. Coordinator regex rejects
        # them; producer template MUST match.
        assert _producer_permalink("octo/widgets", SHA, "src/file.rs") is None

    def test_malformed_range_missing_end(self):
        # "file.rs:1-" has `-` but no end digit. Coordinator rejects; producer
        # MUST match — emitting `#L1` here would silently drift from coordinator.
        assert _producer_permalink("octo/widgets", SHA, "src/file.rs:1-") is None

    def test_malformed_range_missing_start(self):
        # "file.rs:-2" has `-` but no start digit. Same rule.
        assert _producer_permalink("octo/widgets", SHA, "src/file.rs:-2") is None


# ---------------------------------------------------------------------------
# URL-encoding for unsafe path characters
# ---------------------------------------------------------------------------
class TestPathEncoding:
    def test_space_in_path(self):
        url = _producer_permalink("octo/widgets", SHA, "src/file name.rs:1")
        assert url is not None
        assert " " not in url
        assert "file%20name.rs" in url

    def test_unicode_in_path(self):
        url = _producer_permalink("octo/widgets", SHA, "src/café.rs:1")
        assert url is not None
        assert "café" not in url
        assert "%C3%A9" in url

    def test_hash_in_path_does_not_split_anchor(self):
        url = _producer_permalink("octo/widgets", SHA, "src/weird#name.rs:1")
        assert url is not None
        # Only the line anchor `#` survives; the path `#` is encoded.
        assert url.count("#") == 1
        assert "%23" in url

    def test_slashes_preserved(self):
        url = _producer_permalink("octo/widgets", SHA, "a/b/c/file.rs:1")
        assert url is not None
        assert "/a/b/c/file.rs" in url


# ---------------------------------------------------------------------------
# Cross-check: producer output matches consolidator output
# ---------------------------------------------------------------------------
class TestProducerCoordinatorParity:
    """When the consolidator does run, it MUST produce the same URL the
    producer would have. Otherwise an end-to-end pipeline would flip the
    location_permalink on every consolidate pass, which is precisely the
    drift we want to prevent.
    """

    def test_single_line_matches(self):
        prod = _producer_permalink("octo/widgets", SHA, "src/auth.rs:42")
        coord = cr._build_permalink(
            {"owner": "octo", "repo": "widgets"}, SHA, "src/auth.rs:42"
        )
        assert prod == coord

    def test_range_matches(self):
        prod = _producer_permalink("octo/widgets", SHA, "src/auth.rs:42-56")
        coord = cr._build_permalink(
            {"owner": "octo", "repo": "widgets"}, SHA, "src/auth.rs:42-56"
        )
        assert prod == coord

    def test_unicode_path_matches(self):
        prod = _producer_permalink("octo/widgets", SHA, "src/café.rs:1")
        coord = cr._build_permalink(
            {"owner": "octo", "repo": "widgets"}, SHA, "src/café.rs:1"
        )
        assert prod == coord

    def test_missing_pieces_both_return_none(self):
        # Producer and coordinator agree on the "give up" condition.
        assert _producer_permalink("octo/widgets", "", "src/x.rs:1") is None
        assert (
            cr._build_permalink({"owner": "octo", "repo": "widgets"}, "", "src/x.rs:1")
            is None
        )

    def test_path_only_both_return_none(self):
        # Path-only: producer rejects (per tightened contract), coordinator
        # rejects (regex requires `:line` suffix).
        assert _producer_permalink("octo/widgets", SHA, "src/x.rs") is None
        assert (
            cr._build_permalink({"owner": "octo", "repo": "widgets"}, SHA, "src/x.rs")
            is None
        )

    def test_malformed_range_both_return_none(self):
        # "file.rs:1-" rejected by both sides.
        assert _producer_permalink("octo/widgets", SHA, "src/x.rs:1-") is None
        assert (
            cr._build_permalink(
                {"owner": "octo", "repo": "widgets"}, SHA, "src/x.rs:1-"
            )
            is None
        )
