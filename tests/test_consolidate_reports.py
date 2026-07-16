"""Comprehensive tests for consolidate_reports.py."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def make_finding():
    """Factory for creating finding dicts with sensible defaults."""

    def _make(
        *,
        severity: int = 3,
        title: str = "Test finding",
        location: str = "src/main.rs:10-20",
        description: str = "A test finding",
        recommendation: str = "Fix it",
        original_id: str = "",
        tags: list[str] | None = None,
        fid: str | None = None,
    ) -> dict[str, Any]:
        f: dict[str, Any] = {
            "severity": severity,
            "title": title,
            "location": location,
            "description": description,
            "recommendation": recommendation,
        }
        if original_id:
            f["original_id"] = original_id
        if tags is not None:
            f["tags"] = tags
        if fid is not None:
            f["id"] = fid
        return f

    return _make


@pytest.fixture
def make_section():
    """Factory for creating finding_section dicts."""

    def _make(
        *,
        category: str = "code_quality",
        title: str = "Code Quality",
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "title": title,
            "category": category,
            "findings": findings if findings is not None else [],
        }

    return _make


@pytest.fixture
def schema_path():
    """Path to the review-report schema."""
    return (
        Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
    )


# ---------------------------------------------------------------------------
# parse_location
# ---------------------------------------------------------------------------
class TestParseLocation:
    def test_normal_range(self):
        assert cr.parse_location("src/auth.rs:42-56") == ("src/auth.rs", 42, 56)

    def test_single_line(self):
        assert cr.parse_location("file.py:10") == ("file.py", 10, 10)

    def test_no_line(self):
        assert cr.parse_location("file.py") == ("file.py", None, None)

    def test_empty_string(self):
        assert cr.parse_location("") == ("", None, None)

    def test_path_with_directory_colon(self):
        # Windows-style path: C:\foo\bar.py:10
        result = cr.parse_location("C:\\foo\\bar.py:10")
        assert result == ("C:\\foo\\bar.py", 10, 10)

    def test_path_with_no_digits_after_colon(self):
        # e.g. "some:file" where after colon there are no digits
        result = cr.parse_location("some:file")
        assert result == ("some:file", None, None)


# ---------------------------------------------------------------------------
# _similarity_score
# ---------------------------------------------------------------------------
class TestSimilarityScore:
    def test_overlapping_same_file(self):
        f1 = {"location": "src/main.rs:10-20", "title": "A"}
        f2 = {"location": "src/main.rs:15-25", "title": "B"}
        score, _ = cr._similarity_score(f1, f2)
        assert score >= 0.3  # overlap contributes 1.0 * 0.3 = 0.3

    def test_adjacent_lines(self):
        f1 = {"location": "src/main.rs:10-15", "title": "X"}
        f2 = {"location": "src/main.rs:20-25", "title": "Y"}
        score, _ = cr._similarity_score(f1, f2)
        assert score >= 0.18  # adjacent contributes 0.6 * 0.3 = 0.18

    def test_similar_titles(self):
        f1 = {"location": "a.rs:1", "title": "Missing error handling in auth module"}
        f2 = {"location": "b.rs:1", "title": "Missing error handling in auth module"}
        score, _ = cr._similarity_score(f1, f2)
        # Title similarity of 1.0 * 0.5 = 0.5
        assert score >= 0.49

    def test_different_files_different_titles(self):
        f1 = {"location": "src/auth.rs:10-20", "title": "SQL injection"}
        f2 = {"location": "lib/util.py:100-200", "title": "Unused import"}
        score, _ = cr._similarity_score(f1, f2)
        assert score < 0.4

    def test_score_in_range(self):
        f1 = {"location": "same.rs:1-100", "title": "Same title exactly"}
        f2 = {"location": "same.rs:1-100", "title": "Same title exactly"}
        score, _ = cr._similarity_score(f1, f2)
        assert 0.0 <= score <= 1.0

    def test_missing_location_no_crash(self):
        f1 = {"title": "A"}
        f2 = {"title": "B"}
        score, _ = cr._similarity_score(f1, f2)
        assert score >= 0.0

    def test_empty_titles(self):
        f1 = {"location": "a.rs:1", "title": ""}
        f2 = {"location": "a.rs:1", "title": ""}
        score, _ = cr._similarity_score(f1, f2)
        # Empty titles don't add to score, overlap contributes 1.0 * 0.3 = 0.3
        assert score >= 0.3


# ---------------------------------------------------------------------------
# find_duplicate_groups
# ---------------------------------------------------------------------------
class TestFindDuplicateGroups:
    def test_no_duplicates(self):
        findings = [
            {"location": "a.rs:1", "title": "Alpha"},
            {"location": "z.py:999", "title": "Omega"},
        ]
        groups = cr.find_duplicate_groups(findings, threshold=0.9)
        assert groups == []

    def test_two_similar(self):
        findings = [
            {"location": "a.rs:10-20", "title": "Missing error handling"},
            {"location": "a.rs:12-18", "title": "Missing error handling"},
        ]
        groups = cr.find_duplicate_groups(findings, threshold=0.6)
        assert len(groups) == 1
        assert sorted(groups[0]["finding_indices"]) == [0, 1]

    def test_transitive_closure(self):
        # A~B overlapping, B~C overlapping, A and C may not overlap directly
        findings = [
            {"location": "f.rs:10-20", "title": "Error handling"},
            {"location": "f.rs:18-30", "title": "Error handling"},
            {"location": "f.rs:28-40", "title": "Error handling"},
        ]
        groups = cr.find_duplicate_groups(findings, threshold=0.6)
        assert len(groups) == 1
        assert sorted(groups[0]["finding_indices"]) == [0, 1, 2]

    def test_single_finding(self):
        findings = [{"location": "a.rs:1", "title": "Solo"}]
        groups = cr.find_duplicate_groups(findings)
        assert groups == []

    def test_threshold_boundary_below(self):
        # Force score just below threshold
        findings = [
            {"location": "a.rs:1", "title": "X"},
            {"location": "b.rs:999", "title": "Y"},
        ]
        groups = cr.find_duplicate_groups(findings, threshold=0.99)
        assert groups == []

    def test_threshold_boundary_above(self):
        # Identical findings should exceed any reasonable threshold
        findings = [
            {"location": "a.rs:10-20", "title": "Same title"},
            {"location": "a.rs:10-20", "title": "Same title"},
        ]
        groups = cr.find_duplicate_groups(findings, threshold=0.7)
        assert len(groups) == 1

    def test_empty_list(self):
        assert cr.find_duplicate_groups([]) == []

    def test_exact_path_delegates_to_shared_adjacency_helper(self):
        """The exact path must not carry its own inline BFS — it builds the
        same adjacency graph and delegates to _groups_from_adjacency, the
        helper the bucketed (degraded) path also uses."""
        findings = [
            {"location": "f.rs:10-20", "title": "Error handling"},
            {"location": "f.rs:18-30", "title": "Error handling"},
            {"location": "f.rs:28-40", "title": "Error handling"},
        ]
        n = len(findings)
        adj: dict[int, set[int]] = defaultdict(set)
        pair_reasons: dict[tuple[int, int], str] = {}
        for i in range(n):
            for j in range(i + 1, n):
                score, reason = cr._similarity_score(findings[i], findings[j])
                if score >= cr.SIMILARITY_THRESHOLD:
                    adj[i].add(j)
                    adj[j].add(i)
                    pair_reasons[(i, j)] = reason
        expected = cr._groups_from_adjacency(n, adj, pair_reasons)
        assert cr.find_duplicate_groups(findings) == expected

    def test_reason_has_no_leading_empty_segment_from_unexplained_pair(self):
        """A pair whose only matching signal is sub-threshold title
        similarity (score contributes, but too low to earn its own reason
        text) must not leave a stray leading '; ' in the group's combined
        reason string."""
        a = {"location": "", "title": "alpha beta gamma delta", "tags": ["x"]}
        b = {"location": "", "title": "zzzz yyyy xxxx alpha", "tags": ["x"]}
        score, reason = cr._similarity_score(a, b)
        assert reason == ""  # confirms the empty-reason precondition
        assert score >= cr.SIMILARITY_THRESHOLD
        groups = cr.find_duplicate_groups([a, b])
        assert len(groups) == 1
        assert groups[0]["reason"] == ""


# ---------------------------------------------------------------------------
# find_duplicate_groups — threshold-gated degraded (bucketed) path
# ---------------------------------------------------------------------------
def _distinct_findings(count: int) -> list[dict[str, Any]]:
    """`count` findings with unique file + unique title (never form a group)."""
    cats = ["security", "code_quality", "project", "documentation"]
    return [
        {
            "location": f"src/filler{i}.rs:{i}-{i + 5}",
            "title": f"Filler finding {i}",
            "category": cats[i % len(cats)],
            "tags": [],
        }
        for i in range(count)
    ]


def _in_same_group(groups: list[dict[str, Any]], i: int, j: int) -> bool:
    return any(i in g["finding_indices"] and j in g["finding_indices"] for g in groups)


class TestFindDuplicateGroupsBucketed:
    CAP = None  # set in setup_method from the module constant

    def setup_method(self):
        self.CAP = cr.DUP_DETECTION_MAX_FINDINGS

    def test_below_cap_uses_exact_path_and_catches_cross_file_fuzzy(self, caplog):
        # A cross-file / cross-category *near*-duplicate (similar not identical
        # title) IS grouped by the untouched exact path, with no degrade warning.
        near_a = {
            "location": "src/a.rs:1",
            "title": "Alpha beta gamma delta epsilon",
            "category": "security",
            "tags": [],
        }
        near_b = {
            "location": "src/b.rs:1",
            "title": "Alpha beta gamma delta omega",
            "category": "code_quality",
            "tags": [],
        }
        with caplog.at_level(logging.WARNING):
            groups = cr.find_duplicate_groups([near_a, near_b])
        assert len(groups) == 1  # exact path still groups cross-file fuzzy dups
        assert not any("degraded" in r.message.lower() for r in caplog.records)

    def test_above_cap_warns_and_runtime_bounded(self, caplog):
        findings = _distinct_findings(self.CAP * 8)  # e.g. 4000, all distinct
        start = time.perf_counter()
        with caplog.at_level(logging.WARNING):
            groups = cr.find_duplicate_groups(findings)
        elapsed = time.perf_counter() - start
        # Degraded path is near-linear: the old O(n^2) scan took ~70s at 3000.
        assert elapsed < 10.0, f"bucketed dedup too slow: {elapsed:.1f}s"
        assert any("degraded" in r.message.lower() for r in caplog.records), (
            "expected a visible degradation warning"
        )
        assert groups == []  # distinct findings share no bucket or title

    def test_above_cap_catches_same_bucket_fuzzy_and_cross_file_exact_title(self):
        filler = _distinct_findings(self.CAP)
        # Same (category, file) bucket, overlapping lines, identical title.
        sf_a = {
            "location": "src/same.rs:10-20",
            "title": "Missing error handling here",
            "category": "security",
            "tags": [],
        }
        sf_b = {
            "location": "src/same.rs:15-25",
            "title": "Missing error handling here",
            "category": "security",
            "tags": [],
        }
        # Different files AND categories, but an identical (normalized) title.
        xf_a = {
            "location": "src/x.rs:1",
            "title": "Hardcoded credentials in config",
            "category": "security",
            "tags": [],
        }
        xf_b = {
            "location": "lib/y.py:99",
            "title": "hardcoded credentials in config",  # case-normalized match
            "category": "code_quality",
            "tags": [],
        }
        findings = filler + [sf_a, sf_b, xf_a, xf_b]
        assert len(findings) > self.CAP
        groups = cr.find_duplicate_groups(findings)
        n = len(findings)
        assert _in_same_group(groups, n - 4, n - 3)  # same-bucket fuzzy pair
        assert _in_same_group(groups, n - 2, n - 1)  # cross-file exact-title pair

    def test_above_cap_cross_file_near_dup_is_intentionally_missed(self):
        # Different files/categories, similar-but-NOT-identical titles.
        near_a = {
            "location": "src/na.rs:1",
            "title": "Alpha beta gamma delta epsilon",
            "category": "security",
            "tags": [],
        }
        near_b = {
            "location": "src/nb.rs:1",
            "title": "Alpha beta gamma delta omega",
            "category": "code_quality",
            "tags": [],
        }
        # The exact path DOES group them (documents what degraded mode gives up).
        assert len(cr.find_duplicate_groups([near_a, near_b])) == 1
        # Above the cap they are intentionally NOT grouped.
        findings = _distinct_findings(self.CAP) + [near_a, near_b]
        assert len(findings) > self.CAP
        groups = cr.find_duplicate_groups(findings)
        n = len(findings)
        assert not _in_same_group(groups, n - 2, n - 1)

    def test_bucketed_grouping_matches_exact_when_no_cross_file_fuzzy(self):
        # When the only dups are same-bucket fuzzy + cross-file exact-title, the
        # degraded path produces the SAME groups (finding sets) as the exact path.
        def _f(location, title, category):
            return {
                "location": location,
                "title": title,
                "category": category,
                "tags": [],
            }

        findings = [
            _f("src/same.rs:10-20", "Missing error handling", "security"),
            _f("src/same.rs:12-22", "Missing error handling", "security"),
            _f("src/x.rs:1", "Weak crypto default", "security"),
            _f("lib/y.py:5", "Weak crypto default", "code_quality"),
            _f("src/z.rs:99", "Totally unrelated thing", "project"),
        ]
        exact = cr.find_duplicate_groups(findings)  # below cap -> exact path
        bucketed = cr._find_duplicate_groups_bucketed(findings, cr.SIMILARITY_THRESHOLD)
        exact_sets = sorted(tuple(g["finding_indices"]) for g in exact)
        bucketed_sets = sorted(tuple(g["finding_indices"]) for g in bucketed)
        assert exact_sets == bucketed_sets == [(0, 1), (2, 3)]

    def test_oversized_single_bucket_stays_bounded(self, caplog):
        # A mega-file review: 600+ findings all share one (category, file_path)
        # bucket. Without a per-bucket cap, the "degraded" path's own fuzzy
        # scan reproduces the O(n^2) stall it was supposed to avoid.
        count = self.CAP + 100
        findings = [
            {
                "location": "src/mega.rs:1-10",
                "title": f"Finding number {i} about something",
                "category": "security",
                "tags": [],
            }
            for i in range(count)
        ]
        start = time.perf_counter()
        with caplog.at_level(logging.WARNING):
            cr.find_duplicate_groups(findings)
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, f"oversized-bucket dedup too slow: {elapsed:.1f}s"
        assert any(
            "bucket" in r.message.lower() and "src/mega.rs" in r.message
            for r in caplog.records
        ), "expected a warning naming the oversized bucket"


# ---------------------------------------------------------------------------
# assign_ids
# ---------------------------------------------------------------------------
class TestAssignIds:
    def test_category_prefixes(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[make_finding(severity=4, title="SQL injection")],
            ),
            make_section(
                category="project",
                findings=[make_finding(severity=3, title="Config issue")],
            ),
            make_section(
                category="code_quality",
                findings=[make_finding(severity=2, title="Style")],
            ),
            make_section(
                category="dependencies",
                findings=[make_finding(severity=4, title="Vuln dep")],
            ),
            make_section(
                category="documentation",
                findings=[make_finding(severity=1, title="Missing docs")],
            ),
            make_section(
                category="pr_comments",
                findings=[make_finding(severity=2, title="Stale comment")],
            ),
        ]
        cr.assign_ids(sections)
        assert sections[0]["findings"][0]["id"] == "SEC-001"
        assert sections[1]["findings"][0]["id"] == "PROJ-001"
        assert sections[2]["findings"][0]["id"].startswith("CODE-")
        assert sections[3]["findings"][0]["id"] == "DEP-001"
        assert sections[4]["findings"][0]["id"] == "DOC-001"
        assert sections[5]["findings"][0]["id"] == "CMT-001"

    def test_sorted_by_severity(self, make_finding, make_section):
        findings = [
            make_finding(severity=2, title="Low"),
            make_finding(severity=5, title="Critical"),
            make_finding(severity=4, title="High"),
        ]
        sections = [make_section(category="security", findings=findings)]
        cr.assign_ids(sections)
        sevs = [f["severity"] for f in sections[0]["findings"]]
        assert sevs == [5, 4, 2]

    def test_code_fallback_no_original_id(self, make_finding, make_section):
        sections = [
            make_section(
                category="code_quality",
                findings=[make_finding(title="No prefix")],
            ),
        ]
        cr.assign_ids(sections)
        assert sections[0]["findings"][0]["id"].startswith("CODE-")

    def test_detects_rust_prefix(self, make_finding, make_section):
        sections = [
            make_section(
                category="code_quality",
                findings=[
                    make_finding(original_id="RUST-001"),
                    make_finding(original_id="RUST-002"),
                ],
            ),
        ]
        cr.assign_ids(sections)
        assert sections[0]["findings"][0]["id"].startswith("RUST-")

    def test_removes_original_id(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[make_finding(original_id="OLD-001")],
            ),
        ]
        cr.assign_ids(sections)
        assert "original_id" not in sections[0]["findings"][0]

    def test_unknown_severity_no_crash(self, make_finding, make_section):
        """A finding with an out-of-range severity still gets an ID assigned."""
        sections = [
            make_section(
                category="security",
                findings=[make_finding(severity=99)],
            ),
        ]
        cr.assign_ids(sections)
        assert sections[0]["findings"][0]["id"] == "SEC-001"

    def test_in_place_mutation_of_findings(self, make_finding, make_section):
        f = make_finding(severity=4)
        sections = [make_section(category="security", findings=[f])]
        cr.assign_ids(sections)
        # The original finding object should have been mutated
        assert "id" in f

    def test_call_tree_category_gets_call_prefix_and_populates_matrix(
        self, make_finding, make_section
    ):
        """Stream A: the call_tree category must assign sequential CALL-NNN
        IDs and the resulting matrix row must carry the call_tree column."""
        sections = [
            make_section(
                category="call_tree",
                title="Call-Tree Inspection",
                findings=[
                    make_finding(severity=4, title="Unbounded recursion"),
                    make_finding(severity=3, title="Swallowed error two frames deep"),
                ],
            ),
        ]
        cr.assign_ids(sections)
        ids = [f["id"] for f in sections[0]["findings"]]
        assert ids == ["CALL-001", "CALL-002"], ids
        stats = cr.compute_statistics(sections, [])
        matrix_by_sev = {
            row["severity"]: row for row in stats["severity_category_matrix"]
        }
        assert matrix_by_sev["HIGH"]["call_tree"] == 1
        assert matrix_by_sev["MEDIUM"]["call_tree"] == 1
        # The original code_quality column must NOT pick up the call_tree counts —
        # call_tree is its own category, NOT folded into code_quality.
        assert matrix_by_sev["HIGH"]["code_quality"] == 0
        assert matrix_by_sev["MEDIUM"]["code_quality"] == 0


# ---------------------------------------------------------------------------
# compute_statistics
# ---------------------------------------------------------------------------
class TestComputeStatistics:
    def test_empty_findings(self, make_section):
        stats = cr.compute_statistics([], [])
        assert stats["total_findings"] == 0
        assert all(v == 0 for v in stats["severity_counts"].values())

    def test_mixed_severities(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity=5),
                    make_finding(severity=4),
                    make_finding(severity=4),
                ],
            ),
            make_section(
                category="code_quality",
                findings=[make_finding(severity=2)],
            ),
        ]
        stats = cr.compute_statistics(sections, [])
        assert stats["total_findings"] == 4
        assert stats["severity_counts"]["CRITICAL"] == 1
        assert stats["severity_counts"]["HIGH"] == 2
        assert stats["severity_counts"]["LOW"] == 1
        assert stats["severity_counts"]["MEDIUM"] == 0

    def test_all_categories_in_matrix(self, make_section):
        stats = cr.compute_statistics([], [])
        matrix = stats["severity_category_matrix"]
        assert len(matrix) == 5  # one row per severity
        categories_in_row = set(matrix[0].keys()) - {"severity", "total"}
        assert "security" in categories_in_row
        assert "dependencies" in categories_in_row

    def test_redundancy_ratio(self, make_section):
        agent_stats = [
            {"agent": "sec", "unique": 3, "redundant": 7},
            {"agent": "code", "unique": 5, "redundant": 5},
        ]
        stats = cr.compute_statistics([], agent_stats)
        assert stats["redundancy_ratio"] == "60%"

    def test_no_redundancy_ratio_without_agent_stats(self, make_section):
        stats = cr.compute_statistics([], [])
        assert "redundancy_ratio" not in stats

    def test_matrix_cell_values(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity=4),
                    make_finding(severity=4),
                    make_finding(severity=5),
                ],
            ),
            make_section(
                category="project",
                findings=[
                    make_finding(severity=2),
                ],
            ),
            make_section(
                category="code_quality",
                findings=[
                    make_finding(severity=3),
                    make_finding(severity=3),
                ],
            ),
        ]
        stats = cr.compute_statistics(sections, [])
        matrix = stats["severity_category_matrix"]
        matrix_by_sev = {row["severity"]: row for row in matrix}

        assert matrix_by_sev["HIGH"]["security"] == 2
        assert matrix_by_sev["HIGH"]["project"] == 0
        assert matrix_by_sev["HIGH"]["total"] == 2

        assert matrix_by_sev["CRITICAL"]["security"] == 1
        assert matrix_by_sev["CRITICAL"]["total"] == 1

        assert matrix_by_sev["LOW"]["project"] == 1
        assert matrix_by_sev["LOW"]["security"] == 0
        assert matrix_by_sev["LOW"]["total"] == 1

        assert matrix_by_sev["MEDIUM"]["code_quality"] == 2
        assert matrix_by_sev["MEDIUM"]["security"] == 0
        assert matrix_by_sev["MEDIUM"]["total"] == 2

        assert matrix_by_sev["INFO"]["total"] == 0

    def test_merge_class_counts_emitted_only_when_present(
        self, make_finding, make_section
    ):
        absent = [make_section(findings=[make_finding()])]
        assert "merge_class_counts" not in cr.compute_statistics(absent, [])

        blocking = make_finding()
        blocking["merge_class"] = "blocking"
        classified = [make_section(findings=[blocking])]
        assert cr.compute_statistics(classified, [])["merge_class_counts"] == {
            "blocking": 1,
            "non_blocking": 0,
            "out_of_scope_follow_up": 0,
            "disputed": 0,
        }


# ---------------------------------------------------------------------------
# generate_remediation
# ---------------------------------------------------------------------------
class TestGenerateRemediation:
    def _sections_with_severities(self, make_finding, make_section, severities):
        findings = [
            make_finding(severity=s, fid=f"X-{i:03d}") for i, s in enumerate(severities)
        ]
        return [make_section(category="security", findings=findings)]

    def test_critical_before_merge(self, make_finding, make_section):
        sections = self._sections_with_severities(make_finding, make_section, [5])
        result = cr.generate_remediation(sections)
        bm = next(b for b in result if b["priority"] == "before_merge")
        assert bm["count"] == 1

    def test_high_before_merge(self, make_finding, make_section):
        sections = self._sections_with_severities(make_finding, make_section, [4])
        result = cr.generate_remediation(sections)
        bm = next(b for b in result if b["priority"] == "before_merge")
        assert bm["count"] == 1

    def test_medium_before_production(self, make_finding, make_section):
        sections = self._sections_with_severities(make_finding, make_section, [3])
        result = cr.generate_remediation(sections)
        bp = next(b for b in result if b["priority"] == "before_production")
        assert bp["count"] == 1

    def test_low_post_deployment(self, make_finding, make_section):
        sections = self._sections_with_severities(make_finding, make_section, [2])
        result = cr.generate_remediation(sections)
        pd = next(b for b in result if b["priority"] == "post_deployment")
        assert pd["count"] == 1

    def test_info_excluded(self, make_finding, make_section):
        sections = self._sections_with_severities(make_finding, make_section, [1])
        result = cr.generate_remediation(sections)
        for bucket in result:
            assert bucket["count"] == 0

    def test_empty_findings(self, make_section):
        result = cr.generate_remediation([])
        assert len(result) == 3
        for bucket in result:
            assert bucket["count"] == 0

    def test_merge_class_matrix(self, make_finding, make_section):
        blocking_info = make_finding(severity=1, fid="CODE-001")
        blocking_info["merge_class"] = "blocking"
        non_blocking_high = make_finding(severity=4, fid="CODE-002")
        non_blocking_high["merge_class"] = "non_blocking"
        disputed = make_finding(severity=5, fid="CODE-003")
        disputed["merge_class"] = "disputed"
        follow_up = make_finding(severity=5, fid="CODE-004")
        follow_up["merge_class"] = "out_of_scope_follow_up"

        result = cr.generate_remediation(
            [
                make_section(
                    findings=[blocking_info, non_blocking_high, disputed, follow_up]
                )
            ]
        )
        by_priority = {bucket["priority"]: bucket for bucket in result}
        assert by_priority["before_merge"]["finding_ids"] == ["CODE-001"]
        assert by_priority["before_production"]["finding_ids"] == ["CODE-002"]
        assert by_priority["post_deployment"]["finding_ids"] == ["CODE-004"]

    def test_absent_merge_class_keeps_severity_bucketing(
        self, make_finding, make_section
    ):
        sections = self._sections_with_severities(
            make_finding, make_section, [5, 4, 3, 2, 1]
        )
        assert cr.generate_remediation(sections) == [
            {
                "label": "Before Merge",
                "count": 2,
                "priority": "before_merge",
                "finding_ids": ["X-000", "X-001"],
            },
            {
                "label": "Before Production",
                "count": 1,
                "priority": "before_production",
                "finding_ids": ["X-002"],
            },
            {
                "label": "Post Deployment",
                "count": 1,
                "priority": "post_deployment",
                "finding_ids": ["X-003"],
            },
        ]


# ---------------------------------------------------------------------------
# generate_top_findings
# ---------------------------------------------------------------------------
class TestGenerateTopFindings:
    def test_only_critical_and_high(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity=5, fid="SEC-001"),
                    make_finding(severity=4, fid="SEC-002"),
                    make_finding(severity=3, fid="SEC-003"),
                    make_finding(severity=2, fid="SEC-004"),
                    make_finding(severity=1, fid="SEC-005"),
                ],
            ),
        ]
        top = cr.generate_top_findings(sections)
        ids = [f["id"] for f in top]
        assert "SEC-001" in ids
        assert "SEC-002" in ids
        assert "SEC-003" not in ids

    def test_sorted_critical_first(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity=4, fid="SEC-001"),
                    make_finding(severity=5, fid="SEC-002"),
                ],
            ),
        ]
        top = cr.generate_top_findings(sections)
        assert top[0]["severity"] == 5
        assert top[1]["severity"] == 4

    def test_empty_when_no_critical_high(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity=3, fid="SEC-001"),
                    make_finding(severity=2, fid="SEC-002"),
                ],
            ),
        ]
        assert cr.generate_top_findings(sections) == []

    def test_empty_sections(self):
        assert cr.generate_top_findings([]) == []

    def test_missing_title_and_location_no_crash(self, make_section):
        """A high-severity finding missing title/location must not raise KeyError —
        generate_top_findings guards every field it reads."""
        sections = [
            make_section(
                category="security",
                findings=[{"id": "SEC-001", "severity": 5}],
            ),
        ]
        top = cr.generate_top_findings(sections)
        assert len(top) == 1
        assert top[0]["id"] == "SEC-001"
        assert top[0]["title"] == ""
        assert top[0]["location"] == ""

    def test_blocking_low_is_included_before_non_blocking_high(
        self, make_finding, make_section
    ):
        blocking = make_finding(severity=2, fid="CODE-001")
        blocking.update({"merge_class": "blocking", "overall_severity": 0.2})
        high = make_finding(severity=4, fid="CODE-002")
        high.update({"merge_class": "non_blocking", "overall_severity": 0.8})
        top = cr.generate_top_findings([make_section(findings=[high, blocking])])
        assert [finding["id"] for finding in top] == ["CODE-001", "CODE-002"]
        assert top[0]["merge_class"] == "blocking"

    def test_disputed_high_is_excluded(self, make_finding, make_section):
        disputed = make_finding(severity=5, fid="CODE-001")
        disputed["merge_class"] = "disputed"
        non_disputed = make_finding(severity=5, fid="CODE-002")
        non_disputed["merge_class"] = "non_blocking"

        top = cr.generate_top_findings(
            [make_section(findings=[disputed, non_disputed])]
        )

        assert [finding["id"] for finding in top] == ["CODE-002"]


class TestRegenerateDerived:
    def _report(self) -> dict[str, Any]:
        path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "reports"
            / "v3-merge-class.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_recomputes_after_merge_class_flip(self):
        report = self._report()
        finding = report["findings"][0]["findings"][0]
        finding["merge_class"] = "non_blocking"

        cr.regenerate_derived(report)

        assert [item["id"] for item in report["top_findings"]] == ["SEC-001"]
        by_priority = {bucket["priority"]: bucket for bucket in report["remediation"]}
        assert "CODE-001" not in by_priority["before_merge"]["finding_ids"]
        assert "CODE-001" in by_priority["post_deployment"]["finding_ids"]
        assert report["summary_statistics"]["merge_class_counts"]["blocking"] == 0
        assert report["summary_statistics"]["merge_class_counts"]["non_blocking"] == 2

    def test_regenerate_command_revalidates_and_writes_in_place(self, tmp_path):
        path = tmp_path / "report.json"
        report = self._report()
        report["findings"][0]["findings"][0]["merge_class"] = "non_blocking"
        path.write_text(json.dumps(report), encoding="utf-8")

        args = cr.parse_args(["regenerate", str(path)])
        assert cr.cmd_regenerate(args) == 0
        regenerated = json.loads(path.read_text(encoding="utf-8"))
        assert [item["id"] for item in regenerated["top_findings"]] == ["SEC-001"]


# ---------------------------------------------------------------------------
# scan_intentional
# ---------------------------------------------------------------------------
class TestScanIntentional:
    def test_path_traversal_blocked(self, tmp_path):
        # Create a file outside repo root with INTENTIONAL
        outside = tmp_path / "outside"
        outside.mkdir()
        evil_file = outside / "passwd"
        evil_file.write_text("INTENTIONAL: trust me\n")

        repo = tmp_path / "repo"
        repo.mkdir()

        findings = [{"location": "../outside/passwd:1"}]
        results = cr.scan_intentional(findings, str(repo))
        assert results == []

    def test_normal_file_with_intentional(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        src = repo / "src"
        src.mkdir()
        test_file = src / "main.rs"
        test_file.write_text(
            "fn main() {\n"
            "    // INTENTIONAL: allow unwrap here for CLI\n"
            "    let x = foo.unwrap();\n"
            "}\n"
        )

        findings = [{"location": "src/main.rs:3-3"}]
        results = cr.scan_intentional(findings, str(repo))
        assert len(results) == 1
        assert "INTENTIONAL" in results[0]["intentional_comment"]

    def test_normal_file_without_intentional(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        test_file = repo / "clean.rs"
        test_file.write_text("fn main() {}\n")

        findings = [{"location": "clean.rs:1"}]
        results = cr.scan_intentional(findings, str(repo))
        assert results == []

    def test_nonexistent_file_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        findings = [{"location": "nonexistent.rs:1"}]
        results = cr.scan_intentional(findings, str(repo))
        assert results == []

    def test_finding_without_line_skipped(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        findings = [{"location": "file.rs"}]
        results = cr.scan_intentional(findings, str(repo))
        assert results == []


# ---------------------------------------------------------------------------
# _validate_report
# ---------------------------------------------------------------------------
class TestValidateReport:
    def test_valid_report_returns_true(self):
        report = {
            "schema_version": "3.0.0",
            "metadata": {"project": "test", "date": "2026-03-05"},
            "executive_summary": {"overall_assessment": "All good"},
            "summary_statistics": {
                "total_findings": 0,
                "severity_counts": {
                    "CRITICAL": 0,
                    "HIGH": 0,
                    "MEDIUM": 0,
                    "LOW": 0,
                    "INFO": 0,
                },
            },
            "findings": [],
        }
        assert cr._validate_report(report) is True

    def test_invalid_report_returns_false(self):
        report = {"schema_version": "3.0.0"}  # missing required fields
        result = cr._validate_report(report)
        assert result is False

    def test_returns_bool_type(self):
        report = {
            "schema_version": "3.0.0",
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "summary_statistics": {
                "total_findings": 0,
                "severity_counts": {},
            },
            "findings": [],
        }
        result = cr._validate_report(report)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _flatten_agent_report
# ---------------------------------------------------------------------------
class TestFlattenAgentReport:
    def test_normal_section_with_findings(self):
        sections = [
            {
                "category": "security",
                "title": "Security Review",
                "positives": "Good auth setup",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 4,
                        "title": "SQL injection",
                        "tags": ["sql", "injection"],
                        "location": "src/db.rs:10-20",
                        "description": "Unsafe query",
                        "impact_description": "Data breach",
                        "recommendation": "Use parameterized queries",
                    }
                ],
            }
        ]
        raw, positives = cr._flatten_agent_report("sec-agent", sections)

        assert len(raw) == 1
        f = raw[0]
        assert f["agent"] == "sec-agent"
        assert f["original_id"] == "SEC-001"
        assert f["category"] == "security"
        assert f["section_title"] == "Security Review"
        assert f["severity"] == 4
        assert f["title"] == "SQL injection"
        assert f["tags"] == ["sql", "injection"]
        assert f["location"] == "src/db.rs:10-20"
        assert f["description"] == "Unsafe query"
        assert f["impact_description"] == "Data breach"
        assert f["recommendation"] == "Use parameterized queries"

        assert len(positives) == 1
        assert positives[0]["category"] == "security"
        assert positives[0]["agent"] == "sec-agent"
        assert positives[0]["text"] == "Good auth setup"

    def test_missing_optional_fields_get_defaults(self):
        sections = [
            {
                "category": "code_quality",
                "title": "CQ",
                "findings": [
                    {
                        "severity": 2,
                        "title": "Minor issue",
                        "location": "f.py:1",
                        "description": "Desc",
                        "recommendation": "Fix",
                    }
                ],
            }
        ]
        raw, positives = cr._flatten_agent_report("agent-a", sections)

        assert len(raw) == 1
        f = raw[0]
        assert f.get("tags", []) == []
        assert f.get("impact_description", "") == ""
        # original_id is empty string, stripped by _strip_none_values
        assert "original_id" not in f or f["original_id"] == ""
        assert positives == []

    def test_merge_class_and_intent_basis_pass_through(self):
        sections = [
            {
                "category": "code_quality",
                "title": "CQ",
                "findings": [
                    {
                        "severity": 2,
                        "merge_class": "blocking",
                        "intent_basis": "The requested behavior is absent.",
                        "title": "Missing behavior",
                        "location": "f.py:1",
                        "description": "Desc",
                        "recommendation": "Fix",
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-a", sections)
        assert raw[0]["merge_class"] == "blocking"
        assert raw[0]["intent_basis"] == "The requested behavior is absent."

    def test_empty_sections_list(self):
        raw, positives = cr._flatten_agent_report("agent-x", [])
        assert raw == []
        assert positives == []

    def test_invalid_severity_skipped(self):
        """Findings with out-of-range numeric severity should be skipped."""
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": 42,
                        "title": "Bad sev",
                        "location": "f.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-b", sections)
        assert len(raw) == 0

    def test_string_severity_rejected(self):
        """String severity values must be rejected — only integers 1-5 accepted."""
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": "HIGH",
                        "title": "String finding",
                        "location": "f.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-str", sections)
        assert len(raw) == 0

    def test_non_list_tags_handled_gracefully(self):
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": 3,
                        "title": "Tag issue",
                        "tags": "not-a-list",
                        "location": "f.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-c", sections)
        assert len(raw) == 1
        # With SEC-001 fix, non-list tags default to empty list
        assert raw[0]["tags"] == []

    def test_missing_required_fields_skipped(self):
        """Findings missing required fields (title/location/etc) are skipped."""
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": 4,
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-d", sections)
        assert len(raw) == 0

    def test_empty_title_skipped(self):
        """Finding with empty title is skipped."""
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": 4,
                        "title": "",
                        "location": "f.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        raw, _ = cr._flatten_agent_report("agent-e", sections)
        assert len(raw) == 0


# ---------------------------------------------------------------------------
# CLI integration: cmd_prepare
# ---------------------------------------------------------------------------
class TestCmdPrepare:
    def _make_agent_report(self, tmp_path, name: str, sections: list) -> str:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(sections))
        return f"{name}:{path}"

    def test_valid_input_produces_intermediate(self, tmp_path):
        sections = [
            {
                "category": "security",
                "title": "Security",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 4,
                        "title": "SQL injection",
                        "location": "src/db.rs:10-20",
                        "description": "Bad query",
                        "recommendation": "Use parameterized queries",
                    }
                ],
            }
        ]
        spec = self._make_agent_report(tmp_path, "sec-agent", sections)
        output = tmp_path / "intermediate.json"

        args = argparse.Namespace(
            agent_reports=[spec],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        rc = cr.cmd_prepare(args)
        assert rc == 0
        assert output.exists()
        data = json.loads(output.read_text())
        assert len(data["raw_findings"]) == 1
        assert data["agents"] == ["sec-agent"]

    def test_flat_finding_array_is_auto_wrapped_with_warning(self, tmp_path, caplog):
        findings = [
            {
                "id": "PY-001",
                "severity": 3,
                "risk": 0.4,
                "impact": 0.5,
                "scope": 0.2,
                "title": "Bare finding",
                "location": "scripts/example.py:1",
                "description": "A finding without a section wrapper.",
                "recommendation": "Preserve it.",
            }
        ]
        spec = self._make_agent_report(tmp_path, "python-agent", findings)
        output = tmp_path / "intermediate.json"
        args = argparse.Namespace(
            agent_reports=[spec],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )

        with caplog.at_level(logging.WARNING):
            rc = cr.cmd_prepare(args)

        assert rc == 0
        data = json.loads(output.read_text())
        assert len(data["raw_findings"]) == 1
        assert data["raw_findings"][0]["original_id"] == "PY-001"
        assert data["raw_findings"][0]["category"] == "code_quality"
        assert "auto-wrapping" in caplog.text

    def test_missing_file_returns_2(self, tmp_path):
        output = tmp_path / "out.json"
        args = argparse.Namespace(
            agent_reports=["agent:/nonexistent/path.json"],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        rc = cr.cmd_prepare(args)
        assert rc == 2

    def test_oversized_file_returns_2(self, tmp_path):
        big = tmp_path / "big.json"
        # Write just over 8 MB
        big.write_text("[" + " " * (8 * 1024 * 1024) + "]")
        output = tmp_path / "out.json"
        args = argparse.Namespace(
            agent_reports=[f"agent:{big}"],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        rc = cr.cmd_prepare(args)
        assert rc == 2

    def test_output_dir_created(self, tmp_path):
        sections = [{"category": "code_quality", "title": "CQ", "findings": []}]
        spec = self._make_agent_report(tmp_path, "a", sections)
        output = tmp_path / "subdir" / "deep" / "intermediate.json"

        args = argparse.Namespace(
            agent_reports=[spec],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        rc = cr.cmd_prepare(args)
        assert rc == 0
        assert output.exists()


# ---------------------------------------------------------------------------
# CLI integration: cmd_assemble
# ---------------------------------------------------------------------------
class TestCmdAssemble:
    def _make_assemble_input(self, tmp_path, overrides: dict | None = None) -> Path:
        data: dict[str, Any] = {
            "metadata": {"project": "test-proj", "date": "2026-03-05"},
            "executive_summary": {"overall_assessment": "Looks good"},
            "findings": [
                {
                    "title": "Security Findings",
                    "category": "security",
                    "findings": [
                        {
                            "severity": 4,
                            "title": "SQL injection",
                            "location": "src/db.rs:10-20",
                            "description": "Bad query",
                            "recommendation": "Parameterize",
                            "tags": [],
                            "risk": 0.7,
                            "impact": 0.7,
                            "scope": 1.0,
                        }
                    ],
                }
            ],
            "agent_stats": [],
        }
        if overrides:
            data.update(overrides)
        p = tmp_path / "input.json"
        p.write_text(json.dumps(data))
        return p

    def test_valid_input_produces_report(self, tmp_path):
        inp = self._make_assemble_input(tmp_path)
        output = tmp_path / "report.json"

        args = argparse.Namespace(input=str(inp), output=str(output))
        rc = cr.cmd_assemble(args)
        assert rc == 0
        assert output.exists()
        report = json.loads(output.read_text())
        # The coordinator stamps the current schema version (read from the
        # schema file), which advanced to 3.1.0 — assert against that, not a
        # frozen literal, so the test tracks the schema rather than rotting.
        assert report["schema_version"] == cr.SCHEMA_VERSION
        assert report["summary_statistics"]["total_findings"] == 1

    def test_missing_input_returns_2(self, tmp_path):
        args = argparse.Namespace(
            input="/nonexistent/input.json",
            output=str(tmp_path / "out.json"),
        )
        rc = cr.cmd_assemble(args)
        assert rc == 2

    def test_invalid_schema_returns_1(self, tmp_path):
        # Produce a report that will fail schema validation:
        # Use invalid severity to cause schema validation failure
        data = {
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "findings": [
                {
                    "title": "Bad",
                    "category": "security",
                    "findings": [
                        {
                            "severity": 99,
                            "title": "T",
                            "location": "f:1",
                            "description": "D",
                            "recommendation": "R",
                        }
                    ],
                }
            ],
            "agent_stats": [],
        }
        inp = tmp_path / "bad_input.json"
        inp.write_text(json.dumps(data))
        output = tmp_path / "out.json"

        args = argparse.Namespace(input=str(inp), output=str(output))
        rc = cr.cmd_assemble(args)
        assert rc == 1

    def test_oversized_input_returns_2(self, tmp_path):
        big = tmp_path / "big.json"
        big.write_text("{" + " " * (8 * 1024 * 1024 + 1) + "}")
        args = argparse.Namespace(input=str(big), output=str(tmp_path / "out.json"))
        rc = cr.cmd_assemble(args)
        assert rc == 2

    def test_output_dir_created(self, tmp_path):
        inp = self._make_assemble_input(tmp_path)
        output = tmp_path / "sub" / "dir" / "report.json"

        args = argparse.Namespace(input=str(inp), output=str(output))
        rc = cr.cmd_assemble(args)
        assert rc == 0
        assert output.exists()


# ---------------------------------------------------------------------------
# Schema-version derivation
# ---------------------------------------------------------------------------
class TestSchemaVersionDerivation:
    """``SCHEMA_VERSION`` and ``ACCEPTED_SCHEMA_VERSIONS`` must both be derived
    from the schema enum — a hard-coded accepted set drifts on the next bump."""

    def _schema_enum(self) -> list[str]:
        schema_path = (
            Path(__file__).resolve().parent.parent
            / "schemas"
            / "review-report.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return schema["properties"]["schema_version"]["enum"]

    def test_accepted_versions_match_schema_enum(self):
        """Anti-drift guard: the accepted set is exactly the schema enum."""
        assert cr.ACCEPTED_SCHEMA_VERSIONS == set(self._schema_enum())

    def test_schema_version_is_newest_enum_entry(self):
        assert cr.SCHEMA_VERSION == self._schema_enum()[-1]
        assert cr.SCHEMA_VERSION in cr.ACCEPTED_SCHEMA_VERSIONS


# ---------------------------------------------------------------------------
# Non-finite (NaN/Infinity) rejection at parse time
# ---------------------------------------------------------------------------
class TestNonFiniteRejection:
    """Bare NaN/Infinity JSON constants must be rejected at load, not silently
    fed into the severity math (NaN sinks CRITICAL to INFO; +Inf forces CRITICAL)."""

    def _finding(self, **over: Any) -> dict[str, Any]:
        f = {
            "id": "SEC-001",
            "severity": 4,
            "title": "T",
            "location": "src/db.rs:1",
            "description": "D",
            "recommendation": "R",
            "risk": 0.95,
            "impact": 0.95,
            "scope": 0.95,
        }
        f.update(over)
        return f

    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_prepare_rejects_non_finite_axis(self, tmp_path, bad):
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [self._finding(scope=bad)],
            }
        ]
        agent = tmp_path / "agent.json"
        agent.write_text(json.dumps(sections))  # json.dumps emits bare NaN/Infinity
        output = tmp_path / "out.json"
        args = argparse.Namespace(
            agent_reports=[f"sec:{agent}"],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        assert cr.cmd_prepare(args) == 2
        assert not output.exists()

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")], ids=["nan", "inf"])
    def test_assemble_rejects_non_finite_axis(self, tmp_path, bad):
        data = {
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "findings": [
                {
                    "title": "Sec",
                    "category": "security",
                    "findings": [self._finding(risk=bad)],
                }
            ],
            "agent_stats": [],
        }
        inp = tmp_path / "in.json"
        inp.write_text(json.dumps(data))
        output = tmp_path / "out.json"
        args = argparse.Namespace(input=str(inp), output=str(output))
        assert cr.cmd_assemble(args) == 2
        assert not output.exists()


# ---------------------------------------------------------------------------
# Required-field guard in cmd_assemble (Bug: bare KeyError on dropped field)
# ---------------------------------------------------------------------------
class TestAssembleRequiredFieldGuard:
    def _input_missing_field(self, tmp_path, drop: str) -> Path:
        finding = {
            "severity": 5,  # high enough to reach generate_top_findings
            "title": "Critical bug",
            "location": "src/db.rs:1",
            "description": "D",
            "recommendation": "R",
        }
        finding.pop(drop)
        data = {
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "findings": [
                {"title": "Sec", "category": "security", "findings": [finding]}
            ],
            "agent_stats": [],
        }
        p = tmp_path / "in.json"
        p.write_text(json.dumps(data))
        return p

    @pytest.mark.parametrize(
        "drop", ["title", "location", "description", "recommendation"]
    )
    def test_missing_required_field_exits_1_cleanly(self, tmp_path, caplog, drop):
        inp = self._input_missing_field(tmp_path, drop)
        output = tmp_path / "out.json"
        args = argparse.Namespace(input=str(inp), output=str(output))
        # Must be a clean rc==1, NOT a bare KeyError traceback.
        rc = cr.cmd_assemble(args)
        assert rc == 1
        assert not output.exists()
        assert drop in caplog.text
        assert "required field" in caplog.text

    def test_valid_input_still_assembles(self, tmp_path):
        finding = {
            "severity": 5,
            "title": "Critical bug",
            "location": "src/db.rs:1",
            "description": "D",
            "recommendation": "R",
            "risk": 0.9,
            "impact": 0.9,
            "scope": 0.9,
        }
        data = {
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "findings": [
                {"title": "Sec", "category": "security", "findings": [finding]}
            ],
            "agent_stats": [],
        }
        inp = tmp_path / "in.json"
        inp.write_text(json.dumps(data))
        output = tmp_path / "out.json"
        args = argparse.Namespace(input=str(inp), output=str(output))
        assert cr.cmd_assemble(args) == 0
        assert output.exists()


# ---------------------------------------------------------------------------
# Surrogate-safe JSON output (Bug: UnicodeEncodeError kills the pipeline)
# ---------------------------------------------------------------------------
class TestSurrogateSafeWrite:
    _SURROGATE_TITLE = "Bad title \ud800 lone surrogate"

    def test_prepare_survives_lone_surrogate(self, tmp_path, caplog):
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 4,
                        "title": self._SURROGATE_TITLE,
                        "location": "src/db.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        agent = tmp_path / "agent.json"
        # ensure_ascii=True escapes the surrogate to \ud800 (ASCII-safe on disk);
        # it decodes back to a real lone surrogate on load.
        agent.write_text(json.dumps(sections))
        output = tmp_path / "out.json"
        args = argparse.Namespace(
            agent_reports=[f"sec:{agent}"],
            repo_root=str(tmp_path),
            output=str(output),
            metadata=None,
        )
        rc = cr.cmd_prepare(args)
        assert rc == 0
        assert output.exists()
        text = output.read_text(encoding="utf-8")  # must be valid UTF-8, no crash
        data = json.loads(text)
        # Finding preserved (not silently dropped); surrogate replaced but the
        # surrounding excerpt text is intact.
        assert len(data["raw_findings"]) == 1
        title = data["raw_findings"][0]["title"]
        assert "\ud800" not in text
        assert "\ud800" not in title
        assert "Bad title" in title and "lone surrogate" in title
        assert "SEC-001" in caplog.text  # diagnostic names the offending finding

    def test_assemble_survives_lone_surrogate(self, tmp_path):
        data = {
            "metadata": {"project": "x", "date": "2026-01-01"},
            "executive_summary": {"overall_assessment": "ok"},
            "findings": [
                {
                    "title": "Sec",
                    "category": "security",
                    "findings": [
                        {
                            "severity": 4,
                            "title": self._SURROGATE_TITLE,
                            "location": "src/db.rs:1",
                            "description": "D",
                            "recommendation": "R",
                            "risk": 0.9,
                            "impact": 0.9,
                            "scope": 0.9,
                        }
                    ],
                }
            ],
            "agent_stats": [],
        }
        inp = tmp_path / "in.json"
        inp.write_text(json.dumps(data))
        output = tmp_path / "out.json"
        args = argparse.Namespace(input=str(inp), output=str(output))
        rc = cr.cmd_assemble(args)
        assert rc == 0
        assert output.exists()
        text = output.read_text(encoding="utf-8")
        assert "\ud800" not in text
        assert json.loads(text)["summary_statistics"]["total_findings"] == 1
