#!/usr/bin/env python3
"""Consolidate parallel agent review reports into a single schema-valid report.

Two-phase workflow:
  Phase 1 (prepare): Flatten agent reports, detect duplicates, scan INTENTIONAL comments.
  Phase 2 (assemble): Assign IDs, compute statistics, build schema-valid report.json.

Usage:
    # Phase 1
    python3 scripts/consolidate_reports.py prepare \\
        agent1:path/to/report1.json agent2:path/to/report2.json \\
        --repo-root /path/to/repo --output intermediate.json \\
        [--metadata '{"project":"X","date":"2026-03-05"}']

    # Phase 2
    python3 scripts/consolidate_reports.py assemble \\
        --input merged-findings.json --output report.json

Exit codes:
    0  Success
    1  Validation error
    2  File/parse error
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
)

SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEV_RANK: dict[str, int] = {s: i for i, s in enumerate(SEV_ORDER)}

CATEGORY_PREFIX: dict[str, str] = {
    "security": "SEC-",
    "project": "PROJ-",
    "code_quality": "CODE-",
    "documentation": "DOC-",
    "pr_comments": "CMT-",
    "dependencies": "DEP-",
}

CODE_QUALITY_PREFIXES = {"RUST-", "PY-", "GO-", "FE-"}

MAX_INPUT_SIZE = 8 * 1024 * 1024  # 8 MB


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------
def parse_location(location: str) -> tuple[str, int | None, int | None]:
    """Parse 'file:start-end', 'file:line', or 'file' into (path, start, end)."""
    if not location:
        return ("", None, None)
    # Match last colon followed by digits (handles Windows paths like C:\...)
    m = re.search(r":(\d+)(?:-(\d+))?$", location)
    if not m:
        return (location, None, None)
    file_path = location[: m.start()]
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    return (file_path, start, end)


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
def _similarity_score(f1: dict[str, Any], f2: dict[str, Any]) -> tuple[float, str]:
    """Compute similarity between two findings. Returns (score, reason)."""
    path1, s1, e1 = parse_location(f1.get("location", ""))
    path2, s2, e2 = parse_location(f2.get("location", ""))

    score = 0.0
    reasons: list[str] = []

    if path1 and path2 and path1 == path2:
        if s1 is not None and s2 is not None and e1 is not None and e2 is not None:
            # Overlapping ranges
            if s1 <= e2 and s2 <= e1:
                score += 0.5
                reasons.append(f"overlapping location {path1}:{s1}-{e1} & {s2}-{e2}")
            # Adjacent (within 10 lines)
            elif abs(s1 - e2) <= 10 or abs(s2 - e1) <= 10:
                score += 0.3
                reasons.append(f"adjacent lines in {path1}")

    title1 = f1.get("title", "").lower()
    title2 = f2.get("title", "").lower()
    if title1 and title2:
        title_sim = SequenceMatcher(None, title1, title2).ratio()
        score += title_sim * 0.5
        if title_sim > 0.5:
            reasons.append(f"title similarity {title_sim:.2f}")

    return score, ", ".join(reasons)


def find_duplicate_groups(
    findings: list[dict[str, Any]], threshold: float = 0.6
) -> list[dict[str, Any]]:
    """Find groups of potentially duplicate findings using transitive closure.

    Note: uses transitive closure, so A~B and B~C groups A,B,C together even if
    A and C are dissimilar. Groups are candidates for human review, not auto-merge.
    """
    n = len(findings)
    # Build adjacency with reasons
    adj: dict[int, set[int]] = defaultdict(set)
    pair_reasons: dict[tuple[int, int], str] = {}

    for i in range(n):
        for j in range(i + 1, n):
            score, reason = _similarity_score(findings[i], findings[j])
            if score >= threshold:
                adj[i].add(j)
                adj[j].add(i)
                pair_reasons[(i, j)] = reason

    # Transitive closure via BFS
    visited: set[int] = set()
    groups: list[dict[str, Any]] = []
    group_id = 0

    for start in range(n):
        if start in visited or start not in adj:
            continue
        group_id += 1
        component: set[int] = set()
        queue = [start]
        while queue:
            node = queue.pop()
            if node in component:
                continue
            component.add(node)
            visited.add(node)
            for neighbor in adj[node]:
                if neighbor not in component:
                    queue.append(neighbor)

        # Collect reasons for this group
        all_reasons: list[str] = []
        for i in component:
            for j in component:
                if i < j and (i, j) in pair_reasons:
                    all_reasons.append(pair_reasons[(i, j)])

        groups.append(
            {
                "group_id": group_id,
                "reason": "; ".join(sorted(set(all_reasons))),
                "finding_indices": sorted(component),
            }
        )

    return groups


# ---------------------------------------------------------------------------
# INTENTIONAL scan
# ---------------------------------------------------------------------------
def scan_intentional(
    findings: list[dict[str, Any]], repo_root: str
) -> list[dict[str, Any]]:
    """Scan source files for INTENTIONAL comments near finding locations."""
    results: list[dict[str, Any]] = []
    repo = Path(repo_root)

    for idx, finding in enumerate(findings):
        file_path, start, _end = parse_location(finding.get("location", ""))
        if not file_path or start is None:
            continue

        full_path = (repo / file_path).resolve()
        if not full_path.is_relative_to(repo.resolve()):
            continue
        if not full_path.is_file():
            continue

        try:
            proc = subprocess.run(
                ["grep", "-n", "INTENTIONAL", str(full_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        if proc.returncode != 0:
            continue

        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            m = re.match(r"^(\d+):", line)
            if not m:
                continue
            comment_line = int(m.group(1))
            if abs(comment_line - start) <= 5:
                # Extract the INTENTIONAL(...) content
                comment_text = line[m.end() :].strip()
                results.append(
                    {
                        "finding_index": idx,
                        "intentional_comment": comment_text,
                        "source_line": f"{file_path}:{comment_line}",
                    }
                )
                break

    return results


# ---------------------------------------------------------------------------
# ID assignment
# ---------------------------------------------------------------------------
def _detect_code_quality_prefix(
    findings: list[dict[str, Any]],
) -> str:
    """Detect the language prefix for code_quality findings from original IDs."""
    prefix_counts: dict[str, int] = defaultdict(int)
    for f in findings:
        orig = f.get("original_id", "")
        for pfx in CODE_QUALITY_PREFIXES:
            if orig.startswith(pfx):
                prefix_counts[pfx] += 1
                break
    if prefix_counts:
        return max(prefix_counts, key=lambda k: prefix_counts[k])
    return "CODE-"


def assign_ids(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign sequential IDs to findings in-place, ordered by severity within each category.

    Returns the modified list of sections.
    """
    result: list[dict[str, Any]] = []
    # Track per-category counters
    category_counters: dict[str, int] = defaultdict(int)

    for section in sections:
        cat = section.get("category", "code_quality")
        findings = list(section.get("findings", []))

        # Determine prefix
        if cat == "code_quality":
            prefix = _detect_code_quality_prefix(findings)
        else:
            prefix = CATEGORY_PREFIX.get(cat, "CODE-")

        # Sort by severity (CRITICAL first)
        findings.sort(key=lambda f: SEV_RANK.get(f.get("severity", "INFO"), len(SEV_ORDER)))

        for f in findings:
            category_counters[cat] += 1
            f["id"] = f"{prefix}{category_counters[cat]:03d}"
            # Remove original_id if present (not in schema)
            f.pop("original_id", None)

        new_section = dict(section)
        new_section["findings"] = findings
        result.append(new_section)

    return result


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_statistics(
    sections: list[dict[str, Any]],
    agent_stats: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute summary_statistics from findings and agent_stats."""
    severity_counts: dict[str, int] = {s: 0 for s in SEV_ORDER}
    # category x severity matrix
    categories = list(CATEGORY_PREFIX.keys())
    matrix_data: dict[str, dict[str, int]] = {
        sev: {cat: 0 for cat in categories} for sev in SEV_ORDER
    }

    total = 0
    for section in sections:
        cat = section.get("category", "code_quality")
        for f in section.get("findings", []):
            sev = f.get("severity", "INFO")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            if sev in matrix_data and cat in matrix_data[sev]:
                matrix_data[sev][cat] += 1
            total += 1

    matrix = []
    for sev in SEV_ORDER:
        row: dict[str, Any] = {"severity": sev}
        row_total = 0
        for cat in categories:
            count = matrix_data[sev].get(cat, 0)
            row[cat] = count
            row_total += count
        row["total"] = row_total
        matrix.append(row)

    stats: dict[str, Any] = {
        "total_findings": total,
        "severity_counts": severity_counts,
        "severity_category_matrix": matrix,
    }

    # Redundancy ratio
    if agent_stats:
        total_all = sum(a.get("unique", 0) + a.get("redundant", 0) for a in agent_stats)
        total_redundant = sum(a.get("redundant", 0) for a in agent_stats)
        if total_all > 0:
            ratio = round(total_redundant / total_all * 100)
            stats["redundancy_ratio"] = f"{ratio}%"

    return stats


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------
def generate_remediation(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate remediation priority buckets from findings."""
    buckets: dict[str, dict[str, Any]] = {
        "before_merge": {
            "label": "Before Merge",
            "count": 0,
            "priority": "before_merge",
            "finding_ids": [],
        },
        "before_production": {
            "label": "Before Production",
            "count": 0,
            "priority": "before_production",
            "finding_ids": [],
        },
        "post_deployment": {
            "label": "Post Deployment",
            "count": 0,
            "priority": "post_deployment",
            "finding_ids": [],
        },
    }

    for section in sections:
        for f in section.get("findings", []):
            sev = f.get("severity", "INFO")
            if sev == "INFO":
                continue
            fid = f.get("id", "UNKNOWN")
            if sev in ("CRITICAL", "HIGH"):
                bucket = "before_merge"
            elif sev == "MEDIUM":
                bucket = "before_production"
            else:
                bucket = "post_deployment"
            buckets[bucket]["count"] += 1
            buckets[bucket]["finding_ids"].append(fid)

    return [
        buckets["before_merge"],
        buckets["before_production"],
        buckets["post_deployment"],
    ]


# ---------------------------------------------------------------------------
# Top findings
# ---------------------------------------------------------------------------
def generate_top_findings(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract CRITICAL and HIGH findings as top findings."""
    top: list[dict[str, Any]] = []
    for section in sections:
        for f in section.get("findings", []):
            if f.get("severity") in ("CRITICAL", "HIGH"):
                top.append(
                    {
                        "id": f["id"],
                        "severity": f["severity"],
                        "title": f["title"],
                        "location": f["location"],
                    }
                )
    # Sort: CRITICAL first, then HIGH
    top.sort(key=lambda f: SEV_RANK.get(f["severity"], len(SEV_ORDER)))
    return top


# ---------------------------------------------------------------------------
# Phase 1: prepare
# ---------------------------------------------------------------------------
def _flatten_agent_report(
    agent_name: str, sections: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten agent sections into raw findings and section positives."""
    raw: list[dict[str, Any]] = []
    positives: list[dict[str, Any]] = []

    for section in sections:
        cat = section.get("category", "code_quality")
        section_title = section.get("title", "")
        section_positives = section.get("positives", "")

        if section_positives:
            positives.append(
                {"category": cat, "agent": agent_name, "text": section_positives}
            )

        for f in section.get("findings", []):
            raw.append(
                {
                    "agent": agent_name,
                    "original_id": f.get("id", ""),
                    "category": cat,
                    "section_title": section_title,
                    "severity": f.get("severity", "INFO"),
                    "title": f.get("title", ""),
                    "tags": f.get("tags", []),
                    "location": f.get("location", ""),
                    "description": f.get("description", ""),
                    "impact": f.get("impact", ""),
                    "recommendation": f.get("recommendation", ""),
                    "positives": section_positives if section_positives else None,
                }
            )

    return raw, positives


def cmd_prepare(args: argparse.Namespace) -> int:
    """Execute the prepare phase."""
    raw_findings: list[dict[str, Any]] = []
    section_positives: list[dict[str, Any]] = []
    agents: list[str] = []

    for spec in args.agent_reports:
        if ":" not in spec:
            log.error("Invalid agent spec (expected agent:path): %s", spec)
            return 2
        agent_name, path_str = spec.split(":", 1)
        agents.append(agent_name)

        report_path = Path(path_str)
        try:
            if report_path.stat().st_size > MAX_INPUT_SIZE:
                log.error("Input file too large (>8 MB): %s", path_str)
                return 2
        except FileNotFoundError:
            log.error("Report not found: %s", path_str)
            return 2

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log.error("Report not found: %s", path_str)
            return 2
        except json.JSONDecodeError as e:
            log.error("Invalid JSON in %s: %s", path_str, e)
            return 2

        if not isinstance(data, list):
            log.error("Expected JSON array in %s", path_str)
            return 2

        raw, pos = _flatten_agent_report(agent_name, data)
        raw_findings.extend(raw)
        section_positives.extend(pos)

    # Detect duplicates
    dup_groups = find_duplicate_groups(raw_findings)

    # Scan INTENTIONAL comments
    intentional: list[dict[str, Any]] = []
    if args.repo_root:
        intentional = scan_intentional(raw_findings, args.repo_root)

    # Parse metadata
    metadata: dict[str, Any] = {}
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            log.error("Invalid metadata JSON: %s", e)
            return 2

    # Clean None values from raw findings
    for f in raw_findings:
        if f.get("positives") is None:
            del f["positives"]

    output = {
        "metadata": metadata,
        "agents": agents,
        "raw_findings": raw_findings,
        "duplicate_groups": dup_groups,
        "intentional_downgrades": intentional,
        "section_positives": section_positives,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    log.info(
        "Wrote intermediate file: %s (%d findings, %d dup groups, %d intentional)",
        out_path,
        len(raw_findings),
        len(dup_groups),
        len(intentional),
    )
    return 0


# ---------------------------------------------------------------------------
# Phase 2: assemble
# ---------------------------------------------------------------------------
def cmd_assemble(args: argparse.Namespace) -> int:
    """Execute the assemble phase."""
    input_path = Path(args.input)
    try:
        if input_path.stat().st_size > MAX_INPUT_SIZE:
            log.error("Input file too large (>8 MB): %s", args.input)
            return 2
    except FileNotFoundError:
        log.error("Input not found: %s", args.input)
        return 2

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error("Input not found: %s", args.input)
        return 2
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in %s: %s", args.input, e)
        return 2

    metadata = data.get("metadata", {})
    exec_summary = data.get("executive_summary", {})
    findings_sections = data.get("findings", [])
    agent_stats = data.get("agent_stats", [])
    top_override = data.get("top_findings_override")
    remediation_override = data.get("remediation_override")

    # Assign IDs
    findings_sections = assign_ids(findings_sections)

    # Compute statistics
    stats = compute_statistics(findings_sections, agent_stats)

    # Top findings
    if top_override:
        top_findings = top_override
    else:
        top_findings = generate_top_findings(findings_sections)

    # Remediation
    if remediation_override:
        remediation = remediation_override
    else:
        remediation = generate_remediation(findings_sections)

    # Build report
    report: dict[str, Any] = {
        "schema_version": "1.1.0",
        "metadata": metadata,
        "executive_summary": exec_summary,
        "summary_statistics": stats,
        "findings": findings_sections,
    }

    if top_findings:
        report["top_findings"] = top_findings
    if remediation:
        report["remediation"] = remediation
    if agent_stats:
        report["agent_stats"] = agent_stats

    # Validate against schema
    if not _validate_report(report):
        log.error("Report failed schema validation, not writing output")
        return 1

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    log.info("Wrote report: %s (%d findings)", out_path, stats["total_findings"])
    return 0


def _validate_report(report: dict[str, Any]) -> bool:
    """Validate report against the JSON schema.

    Returns True if valid, False if validation fails.
    Requires jsonschema to be installed (ImportError propagates if missing).
    """
    import jsonschema

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("Could not load schema: %s", e)
        return True

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path))
    if errors:
        for err in errors:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            log.error("Schema validation error at %s: %s", path, err.message)
        log.error("Report has %d validation error(s)", len(errors))
        return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Consolidate parallel agent review reports."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # prepare
    p_prepare = sub.add_parser(
        "prepare", help="Phase 1: flatten, detect dups, scan INTENTIONAL"
    )
    p_prepare.add_argument(
        "agent_reports",
        nargs="+",
        help="Agent reports as agent-name:path/to/report.json",
    )
    p_prepare.add_argument(
        "--repo-root", required=True, help="Path to reviewed repo root"
    )
    p_prepare.add_argument(
        "--output", required=True, help="Output intermediate JSON path"
    )
    p_prepare.add_argument("--metadata", default=None, help="JSON metadata string")

    # assemble
    p_assemble = sub.add_parser(
        "assemble", help="Phase 2: assign IDs, compute stats, build report"
    )
    p_assemble.add_argument(
        "--input", required=True, help="Input merged-findings JSON path"
    )
    p_assemble.add_argument("--output", required=True, help="Output report JSON path")

    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        return cmd_prepare(args)
    elif args.command == "assemble":
        return cmd_assemble(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
