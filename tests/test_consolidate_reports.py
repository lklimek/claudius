"""Comprehensive tests for consolidate_reports.py."""

from __future__ import annotations

import argparse
import json
import sys
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
        severity: str = "MEDIUM",
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
def make_section(make_finding):
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
    return Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"


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
        assert score >= 0.5  # overlap contributes 0.5

    def test_adjacent_lines(self):
        f1 = {"location": "src/main.rs:10-15", "title": "X"}
        f2 = {"location": "src/main.rs:20-25", "title": "Y"}
        score, _ = cr._similarity_score(f1, f2)
        assert score >= 0.3  # adjacent contributes 0.3

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
        # Empty titles don't add to score, but overlap does
        assert score >= 0.5


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
        groups = cr.find_duplicate_groups(findings, threshold=0.9)
        assert len(groups) == 1

    def test_empty_list(self):
        assert cr.find_duplicate_groups([]) == []


# ---------------------------------------------------------------------------
# assign_ids
# ---------------------------------------------------------------------------
class TestAssignIds:
    def test_category_prefixes(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[make_finding(severity="HIGH", title="SQL injection")],
            ),
            make_section(
                category="project",
                findings=[make_finding(severity="MEDIUM", title="Config issue")],
            ),
            make_section(
                category="code_quality",
                findings=[make_finding(severity="LOW", title="Style")],
            ),
            make_section(
                category="dependencies",
                findings=[make_finding(severity="HIGH", title="Vuln dep")],
            ),
            make_section(
                category="documentation",
                findings=[make_finding(severity="INFO", title="Missing docs")],
            ),
            make_section(
                category="pr_comments",
                findings=[make_finding(severity="LOW", title="Stale comment")],
            ),
        ]
        result = cr.assign_ids(sections)
        assert result[0]["findings"][0]["id"] == "SEC-001"
        assert result[1]["findings"][0]["id"] == "PROJ-001"
        assert result[2]["findings"][0]["id"].startswith("CODE-")
        assert result[3]["findings"][0]["id"] == "DEP-001"
        assert result[4]["findings"][0]["id"] == "DOC-001"
        assert result[5]["findings"][0]["id"] == "CMT-001"

    def test_sorted_by_severity(self, make_finding, make_section):
        findings = [
            make_finding(severity="LOW", title="Low"),
            make_finding(severity="CRITICAL", title="Critical"),
            make_finding(severity="HIGH", title="High"),
        ]
        sections = [make_section(category="security", findings=findings)]
        result = cr.assign_ids(sections)
        sevs = [f["severity"] for f in result[0]["findings"]]
        assert sevs == ["CRITICAL", "HIGH", "LOW"]

    def test_code_fallback_no_original_id(self, make_finding, make_section):
        sections = [
            make_section(
                category="code_quality",
                findings=[make_finding(title="No prefix")],
            ),
        ]
        result = cr.assign_ids(sections)
        assert result[0]["findings"][0]["id"].startswith("CODE-")

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
        result = cr.assign_ids(sections)
        assert result[0]["findings"][0]["id"].startswith("RUST-")

    def test_removes_original_id(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[make_finding(original_id="OLD-001")],
            ),
        ]
        result = cr.assign_ids(sections)
        assert "original_id" not in result[0]["findings"][0]

    def test_unknown_severity_no_crash(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[make_finding(severity="UNKNOWN")],
            ),
        ]
        result = cr.assign_ids(sections)
        assert result[0]["findings"][0]["id"] == "SEC-001"

    def test_in_place_mutation_of_findings(self, make_finding, make_section):
        f = make_finding(severity="HIGH")
        sections = [make_section(category="security", findings=[f])]
        cr.assign_ids(sections)
        # The original finding object should have been mutated
        assert "id" in f


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
                    make_finding(severity="CRITICAL"),
                    make_finding(severity="HIGH"),
                    make_finding(severity="HIGH"),
                ],
            ),
            make_section(
                category="code_quality",
                findings=[make_finding(severity="LOW")],
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


# ---------------------------------------------------------------------------
# generate_remediation
# ---------------------------------------------------------------------------
class TestGenerateRemediation:
    def _sections_with_severities(self, make_finding, make_section, severities):
        findings = [
            make_finding(severity=s, fid=f"X-{i:03d}")
            for i, s in enumerate(severities)
        ]
        return [make_section(category="security", findings=findings)]

    def test_critical_before_merge(self, make_finding, make_section):
        sections = self._sections_with_severities(
            make_finding, make_section, ["CRITICAL"]
        )
        result = cr.generate_remediation(sections)
        bm = next(b for b in result if b["priority"] == "before_merge")
        assert bm["count"] == 1

    def test_high_before_merge(self, make_finding, make_section):
        sections = self._sections_with_severities(
            make_finding, make_section, ["HIGH"]
        )
        result = cr.generate_remediation(sections)
        bm = next(b for b in result if b["priority"] == "before_merge")
        assert bm["count"] == 1

    def test_medium_before_production(self, make_finding, make_section):
        sections = self._sections_with_severities(
            make_finding, make_section, ["MEDIUM"]
        )
        result = cr.generate_remediation(sections)
        bp = next(b for b in result if b["priority"] == "before_production")
        assert bp["count"] == 1

    def test_low_post_deployment(self, make_finding, make_section):
        sections = self._sections_with_severities(
            make_finding, make_section, ["LOW"]
        )
        result = cr.generate_remediation(sections)
        pd = next(b for b in result if b["priority"] == "post_deployment")
        assert pd["count"] == 1

    def test_info_excluded(self, make_finding, make_section):
        sections = self._sections_with_severities(
            make_finding, make_section, ["INFO"]
        )
        result = cr.generate_remediation(sections)
        for bucket in result:
            assert bucket["count"] == 0

    def test_empty_findings(self, make_section):
        result = cr.generate_remediation([])
        assert len(result) == 3
        for bucket in result:
            assert bucket["count"] == 0


# ---------------------------------------------------------------------------
# generate_top_findings
# ---------------------------------------------------------------------------
class TestGenerateTopFindings:
    def test_only_critical_and_high(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity="CRITICAL", fid="SEC-001"),
                    make_finding(severity="HIGH", fid="SEC-002"),
                    make_finding(severity="MEDIUM", fid="SEC-003"),
                    make_finding(severity="LOW", fid="SEC-004"),
                    make_finding(severity="INFO", fid="SEC-005"),
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
                    make_finding(severity="HIGH", fid="SEC-001"),
                    make_finding(severity="CRITICAL", fid="SEC-002"),
                ],
            ),
        ]
        top = cr.generate_top_findings(sections)
        assert top[0]["severity"] == "CRITICAL"
        assert top[1]["severity"] == "HIGH"

    def test_empty_when_no_critical_high(self, make_finding, make_section):
        sections = [
            make_section(
                category="security",
                findings=[
                    make_finding(severity="MEDIUM", fid="SEC-001"),
                    make_finding(severity="LOW", fid="SEC-002"),
                ],
            ),
        ]
        assert cr.generate_top_findings(sections) == []

    def test_empty_sections(self):
        assert cr.generate_top_findings([]) == []


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
            "schema_version": "1.1.0",
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
        report = {"schema_version": "1.1.0"}  # missing required fields
        result = cr._validate_report(report)
        assert result is False

    def test_returns_bool_type(self):
        report = {
            "schema_version": "1.1.0",
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
                        "severity": "HIGH",
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
                            "severity": "HIGH",
                            "title": "SQL injection",
                            "location": "src/db.rs:10-20",
                            "description": "Bad query",
                            "recommendation": "Parameterize",
                            "tags": [],
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
        assert report["schema_version"] == "1.1.0"
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
                            "severity": "INVALID_SEVERITY",
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
        args = argparse.Namespace(
            input=str(big), output=str(tmp_path / "out.json")
        )
        rc = cr.cmd_assemble(args)
        assert rc == 2

    def test_output_dir_created(self, tmp_path):
        inp = self._make_assemble_input(tmp_path)
        output = tmp_path / "sub" / "dir" / "report.json"

        args = argparse.Namespace(input=str(inp), output=str(output))
        rc = cr.cmd_assemble(args)
        assert rc == 0
        assert output.exists()
