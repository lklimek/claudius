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
from collections.abc import Iterator
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote as _url_quote

from severity_util import (
    SEV_LABELS,
    SEV_ORDER,
    build_merge_class_stats,
    derive_overall,
    derive_severity_int,
    reject_non_finite_constant,
)

try:
    import jsonschema

    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False
    print(
        "WARNING: jsonschema package not installed. "
        "Install with: pip install jsonschema",
        file=sys.stderr,
    )

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
)

CATEGORY_PREFIX: dict[str, str] = {
    "security": "SEC-",
    "project": "PROJ-",
    "code_quality": "CODE-",
    "call_tree": "CALL-",
    "documentation": "DOC-",
    "pr_comments": "CMT-",
    "pr_promises": "PPM-",
    "dependencies": "DEP-",
}

CODE_QUALITY_PREFIXES = {"RUST-", "PY-", "GO-", "FE-"}

MAX_INPUT_SIZE = 8 * 1024 * 1024  # 8 MB

SIMILARITY_THRESHOLD = 0.3

# Above this many findings the exact O(n^2) fuzzy pairwise scan is replaced by a
# bucketed near-linear pass (see find_duplicate_groups). 500 matches the volume
# at which a real review starts risking multi-minute stalls; below it the exact
# algorithm is kept untouched.
DUP_DETECTION_MAX_FINDINGS = 500


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _load_json_file(path: Path, max_size: int = MAX_INPUT_SIZE) -> dict | list:
    """Load and parse a JSON file with size validation.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file exceeds max_size or contains invalid JSON.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}")
    if size > max_size:
        raise ValueError(f"File too large (>{max_size // (1024 * 1024)} MB): {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_non_finite_constant,
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e
    except ValueError as e:
        raise ValueError(f"Non-finite JSON constant in {path}: {e}") from e


def _iter_findings(
    sections: list[dict[str, Any]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (section, finding) tuples from a list of finding sections."""
    for section in sections:
        for finding in section.get("findings", []):
            yield section, finding


def _strip_none_values(d: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of dict with None and empty-string values removed."""
    return {k: v for k, v in d.items() if v is not None and v != ""}


_REQUIRED_FINDING_FIELDS = ("title", "location", "description", "recommendation")


def _find_missing_finding_fields(sections: list[dict[str, Any]]) -> list[str]:
    """Return one error string per finding missing a required non-empty string field.

    The assemble generators (``generate_top_findings`` / ``generate_remediation``)
    and the renderer index these fields directly; a field dropped during an
    LLM-authored merge would otherwise surface as a bare ``KeyError`` before
    schema validation could report it cleanly.
    """
    errors: list[str] = []
    for idx, (_section, f) in enumerate(_iter_findings(sections)):
        if not isinstance(f, dict):
            errors.append(f"finding #{idx}: expected an object")
            continue
        ident = f.get("id") or f.get("original_id") or f.get("title") or f"#{idx}"
        for field in _REQUIRED_FINDING_FIELDS:
            value = f.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"finding {ident!r}: missing or empty required field {field!r}"
                )
    return errors


def _read_schema_versions() -> list[str]:
    """Read the schema_version enum (oldest..newest) from the schema file."""
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        versions = (
            schema.get("properties", {}).get("schema_version", {}).get("enum", [])
        )
        if versions:
            return list(versions)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return ["3.0.0"]


_SCHEMA_VERSIONS = _read_schema_versions()
SCHEMA_VERSION = _SCHEMA_VERSIONS[-1]

# Every enum entry validates (additive 3.0 -> 3.1), derived from the schema so
# the accepted set never drifts from the source on the next version bump.
ACCEPTED_SCHEMA_VERSIONS = set(_SCHEMA_VERSIONS)


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------
def parse_location(location: str) -> tuple[str, int | None, int | None]:
    """Parse 'file:start-end', 'file:line', or 'file' into (path, start, end)."""
    if not location:
        return ("", None, None)
    m = re.search(r":(\d+)(?:-(\d+))?$", location)
    if not m:
        return (location, None, None)
    file_path = location[: m.start()]
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    return (file_path, start, end)


# ---------------------------------------------------------------------------
# Git-derived metadata (permalink construction)
# ---------------------------------------------------------------------------
_GITHUB_REMOTE_RE = re.compile(
    r"\A(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"/(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?/?\Z"
)
_FULL_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


def _derive_metadata_repository(repo_root: str) -> dict[str, str] | None:
    """Parse `git remote get-url origin` into {owner, repo} for GitHub remotes.

    Returns None for non-git directories, missing origin, or non-GitHub remotes.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.info("git remote lookup failed in %s: %s", repo_root, e)
        return None
    if result.returncode != 0:
        log.info("git remote get-url origin returned non-zero in %s", repo_root)
        return None
    url = result.stdout.strip()
    match = _GITHUB_REMOTE_RE.match(url)
    if not match:
        log.info("non-GitHub or unrecognized remote URL %r — skipping", url)
        return None
    return {"owner": match["owner"], "repo": match["repo"]}


def _full_sha(commit: str | None, repo_root: str) -> str | None:
    """Expand a commit ref to full 40-char SHA via `git rev-parse`.

    Returns the SHA as-is when already full; None for empty input or any failure.
    """
    if not commit:
        return None
    if _FULL_SHA_RE.match(commit):
        return commit
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", commit],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.info("git rev-parse failed for %r in %s: %s", commit, repo_root, e)
        return None
    if result.returncode != 0:
        log.info("git rev-parse could not resolve %r in %s", commit, repo_root)
        return None
    full = result.stdout.strip()
    return full if _FULL_SHA_RE.match(full) else None


def _build_permalink(
    repository: dict[str, str] | None,
    sha: str | None,
    location: str,
) -> str | None:
    """Build a GitHub blob URL with line anchors. Returns None when any input is missing.

    The path component is URL-encoded so spaces, unicode, ``#``, and ``?`` in
    a file path do not break the URL or hijack the fragment.
    """
    if not repository or not sha:
        return None
    file_path, start, end = parse_location(location)
    if not file_path or start is None:
        return None
    # Reject control characters outright — they have no place in a URL and
    # would survive into downstream rendering / logging contexts.
    if any(c in file_path for c in "\n\r\t"):
        return None
    safe_path = _url_quote(file_path, safe="/")
    anchor = f"#L{start}" if end is None or end == start else f"#L{start}-L{end}"
    return (
        f"https://github.com/{repository['owner']}/{repository['repo']}"
        f"/blob/{sha}/{safe_path}{anchor}"
    )


# ---------------------------------------------------------------------------
# OWASP severity derivation (shared with the renderer via severity_util)
# ---------------------------------------------------------------------------
# Re-exported under the legacy private names the test-suite imports.
_derive_overall = derive_overall
_derive_severity_int = derive_severity_int


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
def _similarity_score(f1: dict[str, Any], f2: dict[str, Any]) -> tuple[float, str]:
    """Compute normalized similarity (0.0-1.0) between two findings.

    Weighted average: title similarity (50%), location overlap (30%), tag overlap (20%).
    """
    path1, s1, e1 = parse_location(f1.get("location", ""))
    path2, s2, e2 = parse_location(f2.get("location", ""))

    loc_overlap = 0.0
    reasons: list[str] = []

    if path1 and path2 and path1 == path2:
        if s1 is not None and s2 is not None and e1 is not None and e2 is not None:
            if s1 <= e2 and s2 <= e1:
                loc_overlap = 1.0
                reasons.append(f"overlapping location {path1}:{s1}-{e1} & {s2}-{e2}")
            elif abs(s1 - e2) <= 10 or abs(s2 - e1) <= 10:
                loc_overlap = 0.6
                reasons.append(f"adjacent lines in {path1}")

    title1 = f1.get("title", "").lower()
    title2 = f2.get("title", "").lower()
    title_sim = 0.0
    if title1 and title2:
        title_sim = SequenceMatcher(None, title1, title2).ratio()
        if title_sim > 0.5:
            reasons.append(f"title similarity {title_sim:.2f}")

    tags1 = set(f1.get("tags", []))
    tags2 = set(f2.get("tags", []))
    tag_sim = 0.0
    if tags1 or tags2:
        union = tags1 | tags2
        if union:
            tag_sim = len(tags1 & tags2) / len(union)

    score = title_sim * 0.5 + loc_overlap * 0.3 + tag_sim * 0.2
    return score, ", ".join(reasons)


def find_duplicate_groups(
    findings: list[dict[str, Any]], threshold: float = SIMILARITY_THRESHOLD
) -> list[dict[str, Any]]:
    """Find groups of potentially duplicate findings using transitive closure.

    Note: uses transitive closure, so A~B and B~C groups A,B,C together even if
    A and C are dissimilar. Groups are candidates for human review, not auto-merge.

    Above ``DUP_DETECTION_MAX_FINDINGS`` the exact O(n^2) fuzzy scan (below) would
    stall for minutes, so it degrades to a near-linear bucketed pass
    (``_find_duplicate_groups_bucketed``) with a loud warning. That degraded path
    still catches same-(category, file) fuzzy dups and cross-bucket exact-title
    dups, but may miss cross-file *near*-duplicate (similar-not-identical title)
    groups — an accepted, documented trade-off for bounded runtime at scale.
    """
    n = len(findings)
    if n > DUP_DETECTION_MAX_FINDINGS:
        log.warning(
            "Duplicate detection degraded: %d findings exceeds the %d limit, so "
            "the exact O(n^2) pairwise scan is replaced by (category, file_path) "
            "bucketing plus an exact-title cross-bucket pass. Cross-file "
            "near-duplicate (similar but not identical title) groups may be "
            "missed above this limit; split the review to restore exact dedup.",
            n,
            DUP_DETECTION_MAX_FINDINGS,
        )
        return _find_duplicate_groups_bucketed(findings, threshold)

    adj: dict[int, set[int]] = defaultdict(set)
    pair_reasons: dict[tuple[int, int], str] = {}

    for i in range(n):
        for j in range(i + 1, n):
            score, reason = _similarity_score(findings[i], findings[j])
            if score >= threshold:
                adj[i].add(j)
                adj[j].add(i)
                pair_reasons[(i, j)] = reason

    return _groups_from_adjacency(n, adj, pair_reasons)


def _build_agent_stats(
    agents: list[str],
    findings: list[dict[str, Any]],
    duplicate_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Count each agent's findings inside and outside duplicate groups."""
    duplicate_indices = {
        index
        for group in duplicate_groups
        for index in group.get("finding_indices", [])
        if isinstance(index, int)
    }
    counts = {
        agent: {"agent": agent, "unique": 0, "redundant": 0}
        for agent in dict.fromkeys(agents)
    }
    for index, finding in enumerate(findings):
        agent = finding.get("agent")
        if agent not in counts:
            continue
        key = "redundant" if index in duplicate_indices else "unique"
        counts[agent][key] += 1
    return list(counts.values())


def _normalize_title(title: str) -> str:
    """Lowercase and collapse whitespace for exact-title matching."""
    return " ".join(title.lower().split())


def _groups_from_adjacency(
    n: int,
    adj: dict[int, set[int]],
    pair_reasons: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    """Build duplicate groups from a similarity adjacency graph (transitive closure).

    Reasons are collected by walking each component's edges (O(edges)) rather
    than every member pair, keeping the degraded path bounded even for the rare
    large same-title component.
    """
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

        reasons: set[str] = set()
        for i in component:
            for j in adj[i]:
                key = (i, j) if i < j else (j, i)
                reason = pair_reasons.get(key)
                if reason:
                    reasons.add(reason)

        groups.append(
            {
                "group_id": group_id,
                "reason": "; ".join(sorted(reasons)),
                "finding_indices": sorted(component),
            }
        )

    return groups


def _find_duplicate_groups_bucketed(
    findings: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Near-linear degraded duplicate detection for large finding sets.

    Two passes feed one adjacency graph:
    1. Fuzzy ``_similarity_score`` within each ``(category, file_path)`` bucket —
       cheap as long as the bucket stays under ``DUP_DETECTION_MAX_FINDINGS``;
       larger buckets (e.g. a mega-file review) skip the fuzzy scan with a
       warning and fall through to pass 2, preserving the full score's
       location/title/tag reasoning only for bounded buckets.
    2. An O(n) exact-normalized-title pass linking identical titles across
       buckets (chained per title, so transitive closure still groups them all)
       — recovers cross-file *exact*-title duplicates the bucketing alone drops,
       and is the sole recovery path for oversized buckets.

    Cross-file *near*-duplicate (similar but not identical title) groups are
    intentionally not recovered; the caller logs that degradation.
    """
    adj: dict[int, set[int]] = defaultdict(set)
    pair_reasons: dict[tuple[int, int], str] = {}

    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_title: dict[str, list[int]] = defaultdict(list)
    for idx, f in enumerate(findings):
        file_path = parse_location(f.get("location", ""))[0]
        buckets[(f.get("category", ""), file_path)].append(idx)
        norm = _normalize_title(f.get("title", ""))
        if norm:
            by_title[norm].append(idx)

    for key, members in buckets.items():
        if len(members) > DUP_DETECTION_MAX_FINDINGS:
            log.warning(
                "Duplicate detection bucket %s has %d findings, exceeding the "
                "%d per-bucket cap; skipping fuzzy comparison for this bucket "
                "(falls back to exact-title matching only).",
                key,
                len(members),
                DUP_DETECTION_MAX_FINDINGS,
            )
            continue
        for a in range(len(members)):
            i = members[a]
            for b in range(a + 1, len(members)):
                j = members[b]
                score, reason = _similarity_score(findings[i], findings[j])
                if score >= threshold:
                    adj[i].add(j)
                    adj[j].add(i)
                    pair_reasons[(i, j)] = reason

    for norm, members in by_title.items():
        for a in range(len(members) - 1):
            i, j = members[a], members[a + 1]
            lo, hi = (i, j) if i < j else (j, i)
            adj[lo].add(hi)
            adj[hi].add(lo)
            pair_reasons.setdefault((lo, hi), f"identical title {norm!r}")

    return _groups_from_adjacency(len(findings), adj, pair_reasons)


# ---------------------------------------------------------------------------
# INTENTIONAL scan (pure Python, no subprocess)
# ---------------------------------------------------------------------------
def scan_intentional(
    findings: list[dict[str, Any]], repo_root: str
) -> list[dict[str, Any]]:
    """Scan source files for INTENTIONAL comments near finding locations."""
    results: list[dict[str, Any]] = []
    repo = Path(repo_root)
    resolved_repo = repo.resolve()

    # Group findings by file path to avoid re-reading
    file_findings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for idx, finding in enumerate(findings):
        file_path, start, _end = parse_location(finding.get("location", ""))
        if not file_path or start is None:
            continue
        full_path = (repo / file_path).resolve()
        if not full_path.is_relative_to(resolved_repo):
            continue
        if not full_path.is_file():
            continue
        file_findings[file_path].append((idx, start))

    for file_path, idx_starts in file_findings.items():
        full_path = (repo / file_path).resolve()
        try:
            lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        intentional_lines: list[tuple[int, str]] = []
        for line_num_0, line_text in enumerate(lines):
            if "INTENTIONAL" in line_text:
                intentional_lines.append((line_num_0 + 1, line_text.strip()))

        if not intentional_lines:
            continue

        for idx, start in idx_starts:
            for comment_line, comment_text in intentional_lines:
                if abs(comment_line - start) <= 5:
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
) -> None:
    """Assign sequential IDs to findings in-place, ordered by severity within each category."""
    category_counters: dict[str, int] = defaultdict(int)

    for section in sections:
        cat = section.get("category", "code_quality")
        findings = section.get("findings", [])

        if cat == "code_quality":
            prefix = _detect_code_quality_prefix(findings)
        else:
            prefix = CATEGORY_PREFIX.get(cat, "CODE-")

        # Primary: overall_severity desc (absent → -1 so floatless findings sink).
        # Secondary: integer severity desc. Tertiary: stable by current order.
        findings.sort(
            key=lambda f: (
                (
                    f.get("overall_severity", -1.0)
                    if isinstance(f.get("overall_severity"), (int, float))
                    and not isinstance(f.get("overall_severity"), bool)
                    else -1.0
                ),
                f.get("severity", 1),
            ),
            reverse=True,
        )

        for f in findings:
            category_counters[cat] += 1
            f["id"] = f"{prefix}{category_counters[cat]:03d}"
            f.pop("original_id", None)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_statistics(
    sections: list[dict[str, Any]],
    agent_stats: list[Any],
) -> dict[str, Any]:
    """Compute summary_statistics from findings and agent_stats."""
    severity_counts: dict[str, int] = {s: 0 for s in SEV_ORDER}
    categories = list(CATEGORY_PREFIX.keys())
    matrix_data: dict[str, dict[str, int]] = {
        label: {cat: 0 for cat in categories} for label in SEV_ORDER
    }

    total = 0
    for _section, f in _iter_findings(sections):
        cat = _section.get("category", "code_quality")
        sev_int = f.get("severity", 1)
        label = SEV_LABELS.get(sev_int, "INFO")
        severity_counts[label] = severity_counts.get(label, 0) + 1
        if label in matrix_data and cat in matrix_data[label]:
            matrix_data[label][cat] += 1
        total += 1

    matrix = []
    for label in SEV_ORDER:
        row: dict[str, Any] = {"severity": label}
        row_total = 0
        for cat in categories:
            count = matrix_data[label].get(cat, 0)
            row[cat] = count
            row_total += count
        row["total"] = row_total
        matrix.append(row)

    stats: dict[str, Any] = {
        "total_findings": total,
        "severity_counts": severity_counts,
        "severity_category_matrix": matrix,
    }
    merge_class_counts = build_merge_class_stats(
        [finding for _section, finding in _iter_findings(sections)]
    )
    if merge_class_counts:
        stats["merge_class_counts"] = merge_class_counts

    valid_agent_stats = [a for a in agent_stats if isinstance(a, dict)]
    if valid_agent_stats:
        total_all = sum(
            a.get("unique", 0) + a.get("redundant", 0) for a in valid_agent_stats
        )
        total_redundant = sum(a.get("redundant", 0) for a in valid_agent_stats)
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

    for _section, f in _iter_findings(sections):
        sev = f.get("severity", 1)
        fid = f.get("id", "UNKNOWN")
        merge_class = f.get("merge_class")
        if merge_class == "disputed":
            continue
        if merge_class == "blocking":
            bucket = "before_merge"
        elif merge_class == "non_blocking":
            bucket = "before_production" if sev >= 3 else "post_deployment"
        elif merge_class == "out_of_scope_follow_up":
            bucket = "post_deployment"
        elif sev == 1:
            continue
        elif sev >= 4:
            bucket = "before_merge"
        elif sev == 3:
            bucket = "before_production"
        elif sev == 2:
            bucket = "post_deployment"
        else:
            log.warning(
                "Unknown severity '%s' in finding '%s', skipping remediation bucket",
                sev,
                fid,
            )
            continue
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
    """Extract blocking, CRITICAL, and HIGH findings as top findings."""
    top: list[dict[str, Any]] = []
    for _section, f in _iter_findings(sections):
        sev = f.get("severity", 1)
        merge_class = f.get("merge_class")
        if merge_class == "disputed":
            continue
        if merge_class == "blocking" or sev >= 4:
            entry: dict[str, Any] = {
                "id": f.get("id", ""),
                "severity": sev,
                "title": f.get("title", ""),
                "location": f.get("location", ""),
                "_overall_sort": f.get("overall_severity", 0.0),
            }
            if "location_permalink" in f:
                entry["location_permalink"] = f["location_permalink"]
            if "merge_class" in f:
                entry["merge_class"] = f["merge_class"]
            top.append(entry)
    top.sort(
        key=lambda f: (
            f.get("merge_class") == "blocking",
            f.get("severity", 1),
            f.get("_overall_sort", 0.0),
        ),
        reverse=True,
    )
    for finding in top:
        finding.pop("_overall_sort", None)
    return top


def regenerate_derived(report: dict[str, Any]) -> None:
    """Recompute all finding-derived report fields in place."""
    sections = report.get("findings", [])
    report["top_findings"] = generate_top_findings(sections)
    report["remediation"] = generate_remediation(sections)
    report["summary_statistics"] = compute_statistics(
        sections, report.get("agent_stats", [])
    )


# ---------------------------------------------------------------------------
# Output writing (surrogate-safe)
# ---------------------------------------------------------------------------
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _iter_surrogate_fields(obj: Any, path: str = "") -> Iterator[str]:
    """Yield the JSON path of every string value carrying a lone surrogate."""
    if isinstance(obj, str):
        if _SURROGATE_RE.search(obj):
            yield path or "(value)"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_surrogate_fields(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_surrogate_fields(v, f"{path}[{i}]")


def _log_surrogate_findings(findings: list[dict[str, Any]]) -> int:
    """Log each finding field carrying a lone surrogate; return the count found."""
    count = 0
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = f.get("id") or f.get("original_id") or f.get("title") or "<unknown>"
        for field_path in _iter_surrogate_fields(f):
            count += 1
            log.warning(
                "Lone Unicode surrogate in finding %r at %s — sanitizing "
                "(lossy replacement) before write",
                fid,
                field_path,
            )
    return count


def _write_json_output(
    out_path: Path, obj: Any, findings: list[dict[str, Any]]
) -> None:
    """Write ``obj`` as pretty UTF-8 JSON, sanitizing lone surrogates if present.

    ``json.dumps(..., ensure_ascii=False)`` happily emits lone surrogates that
    UTF-8 cannot encode, so one garbled excerpt would otherwise abort the write
    with a ``UnicodeEncodeError`` pointing at a byte offset, not a finding. On
    that error we name the offending finding(s) and re-encode with a lossy
    replacement so no finding is silently dropped.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    try:
        out_path.write_text(text, encoding="utf-8")
    except UnicodeEncodeError:
        if _log_surrogate_findings(findings) == 0:
            log.warning(
                "Non-encodable Unicode (lone surrogate) outside finding fields; "
                "sanitizing (lossy replacement) before write"
            )
        out_path.write_text(text, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Phase 1: prepare
# ---------------------------------------------------------------------------
def _infer_bare_finding_category(findings: list[dict[str, Any]]) -> str:
    """Infer a category from the majority of recognized finding ID prefixes."""
    prefix_categories = {
        prefix: category for category, prefix in CATEGORY_PREFIX.items()
    }
    counts: dict[str, int] = defaultdict(int)
    for finding in findings:
        finding_id = finding.get("id")
        if not isinstance(finding_id, str):
            continue
        for prefix, category in prefix_categories.items():
            if finding_id.startswith(prefix):
                counts[category] += 1
                break

    if not counts:
        return "code_quality"
    highest = max(counts.values())
    winners = [category for category, count in counts.items() if count == highest]
    if len(winners) != 1 or highest * 2 <= sum(counts.values()):
        return "code_quality"
    return winners[0]


def _flatten_agent_report(
    agent_name: str, sections: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten agent sections into raw findings and section positives."""
    finding_markers = {
        "id",
        "risk",
        "impact",
        "scope",
        "location",
        "description",
        "recommendation",
    }
    normalized_sections: list[dict[str, Any]] = []
    stray_findings: list[dict[str, Any]] = []
    for item in sections:
        if (
            isinstance(item, dict)
            and "findings" not in item
            and any(marker in item for marker in finding_markers)
        ):
            stray_findings.append(item)
        else:
            normalized_sections.append(item)

    if stray_findings:
        inferred_category = _infer_bare_finding_category(stray_findings)
        log.warning(
            "Agent '%s' report: rescued %d stray bare finding(s) by auto-wrapping "
            "them in a finding section with inferred category %s",
            agent_name,
            len(stray_findings),
            inferred_category,
        )
        normalized_sections.append(
            {
                "title": f"{agent_name} findings",
                "category": inferred_category,
                "findings": stray_findings,
            }
        )
    sections = normalized_sections

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
            severity = f.get("severity", 1)
            if not isinstance(severity, int) or not 1 <= severity <= 5:
                log.warning(
                    "Skipping finding with invalid severity '%s' from agent '%s'",
                    severity,
                    agent_name,
                )
                continue

            location = f.get("location", "")
            if not isinstance(location, str):
                log.warning(
                    "Skipping finding with non-string location from agent '%s'",
                    agent_name,
                )
                continue

            title = f.get("title", "")
            description = f.get("description", "")
            recommendation = f.get("recommendation", "")
            if not all([location, title, description, recommendation]):
                log.warning(
                    "Skipping finding with empty required field(s) from agent '%s': "
                    "title=%r, location=%r",
                    agent_name,
                    title,
                    location,
                )
                continue

            tags = f.get("tags", [])
            if not isinstance(tags, list):
                tags = []

            entry = _strip_none_values(
                {
                    "agent": agent_name,
                    "original_id": f.get("id", ""),
                    "category": cat,
                    "section_title": section_title,
                    "severity": severity,
                    "risk": f.get("risk"),
                    "impact": f.get("impact"),
                    "scope": f.get("scope"),
                    "title": title,
                    "tags": tags,
                    "location": location,
                    "description": description,
                    "impact_description": f.get("impact_description", ""),
                    "recommendation": recommendation,
                    "code_snippets": f.get("code_snippets"),
                    "merge_class": f.get("merge_class"),
                    "intent_basis": f.get("intent_basis"),
                    "positives": section_positives if section_positives else None,
                }
            )
            raw.append(entry)

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
            data = _load_json_file(report_path)
        except FileNotFoundError:
            log.error("Report not found: %s", path_str)
            return 2
        except ValueError as e:
            log.error("%s", e)
            return 2

        # Detect a legacy v1/v2 envelope dict carrying schema_version and give
        # a version-aware error before the shape check. The plan mandates a
        # hard cutover: v1/v2 must be rejected with a pointer at the schema.
        if isinstance(data, dict):
            declared = data.get("schema_version")
            if (
                isinstance(declared, str)
                and declared
                and declared not in ACCEPTED_SCHEMA_VERSIONS
            ):
                log.error(
                    "Input %s declares schema_version=%r; only %s are accepted. "
                    "v1/v2 reports are no longer supported — re-run the "
                    "producer against the current commit to regenerate. See "
                    "schemas/review-report.schema.json v%s.",
                    path_str,
                    declared,
                    sorted(ACCEPTED_SCHEMA_VERSIONS),
                    SCHEMA_VERSION,
                )
                return 2

        if not isinstance(data, list):
            log.error("Expected JSON array in %s", path_str)
            return 2

        raw, pos = _flatten_agent_report(agent_name, data)
        raw_findings.extend(raw)
        section_positives.extend(pos)

    dup_groups = find_duplicate_groups(raw_findings)
    agent_stats = _build_agent_stats(agents, raw_findings, dup_groups)

    intentional: list[dict[str, Any]] = []
    if args.repo_root:
        intentional = scan_intentional(raw_findings, args.repo_root)

    metadata: dict[str, Any] = {}
    if args.metadata:
        try:
            metadata = json.loads(
                args.metadata, parse_constant=reject_non_finite_constant
            )
        except ValueError as e:
            log.error("Invalid metadata JSON: %s", e)
            return 2

    if args.repo_root:
        repository = _derive_metadata_repository(args.repo_root)
        if repository is not None:
            metadata["repository"] = repository
        full = _full_sha(metadata.get("commit"), args.repo_root)
        if full is not None:
            metadata["commit"] = full
        elif "commit" in metadata:
            metadata.pop("commit")

    output = {
        "metadata": metadata,
        "agents": agents,
        "agent_stats": agent_stats,
        "raw_findings": raw_findings,
        "duplicate_groups": dup_groups,
        "intentional_downgrades": intentional,
        "section_positives": section_positives,
    }

    out_path = Path(args.output)
    _write_json_output(out_path, output, raw_findings)
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
        data = _load_json_file(input_path)
    except FileNotFoundError:
        log.error("Input not found: %s", args.input)
        return 2
    except ValueError as e:
        log.error("%s", e)
        return 2

    metadata = data.get("metadata", {})
    exec_summary = data.get("executive_summary", {})
    findings_sections = data.get("findings", [])
    agent_stats = data.get("agent_stats", [])
    top_override = data.get("top_findings_override")
    remediation_override = data.get("remediation_override")

    # Fail fast on findings missing required fields — the generators below index
    # these directly, so a field dropped during an LLM merge must produce a clean
    # error here rather than a bare KeyError mid-assembly.
    field_errors = _find_missing_finding_fields(findings_sections)
    if field_errors:
        for err in field_errors:
            log.error("%s", err)
        log.error(
            "Input findings failed required-field check (%d error(s)); "
            "fix the merged-findings input and re-run assemble",
            len(field_errors),
        )
        return 1

    repository = metadata.get("repository")
    sha = metadata.get("commit")
    for _section, f in _iter_findings(findings_sections):
        overall = _derive_overall(f)
        if overall is not None:
            f["overall_severity"] = overall
            f["severity"] = _derive_severity_int(overall)
        permalink = _build_permalink(repository, sha, f.get("location", ""))
        if permalink is not None:
            f["location_permalink"] = permalink

    assign_ids(findings_sections)

    stats = compute_statistics(findings_sections, agent_stats)

    if top_override:
        top_findings = top_override
    else:
        top_findings = generate_top_findings(findings_sections)

    if remediation_override:
        remediation = remediation_override
    else:
        remediation = generate_remediation(findings_sections)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
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

    if not _validate_report(report):
        log.error("Report failed schema validation, not writing output")
        return 1

    out_path = Path(args.output)
    _write_json_output(
        out_path, report, [f for _s, f in _iter_findings(findings_sections)]
    )
    log.info("Wrote report: %s (%d findings)", out_path, stats["total_findings"])
    return 0


def _validate_report(report: dict[str, Any]) -> bool:
    """Validate report against the JSON schema.

    Returns True if valid, False if validation fails or schema is unavailable.
    """
    if not _HAS_JSONSCHEMA:
        log.error("jsonschema package not installed, cannot validate report")
        return False

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error("Could not load schema: %s", e)
        return False

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path))
    if errors:
        for err in errors:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            log.error("Schema validation error at %s: %s", path, err.message)
        log.error("Report has %d validation error(s)", len(errors))
        return False
    return True


def cmd_regenerate(args: argparse.Namespace) -> int:
    """Regenerate derived fields in an existing report and write it in place."""
    report_path = Path(args.report)
    try:
        report = _load_json_file(report_path)
    except (FileNotFoundError, ValueError) as error:
        log.error("%s", error)
        return 2
    if not isinstance(report, dict):
        log.error("Expected a report object in %s", report_path)
        return 2

    regenerate_derived(report)
    if not _validate_report(report):
        log.error("Regenerated report failed schema validation, not writing output")
        return 1

    findings = [finding for _section, finding in _iter_findings(report["findings"])]
    _write_json_output(report_path, report, findings)
    log.info("Regenerated derived fields in %s", report_path)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Consolidate parallel agent review reports."
    )
    sub = parser.add_subparsers(dest="command", required=True)

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

    p_assemble = sub.add_parser(
        "assemble", help="Phase 2: assign IDs, compute stats, build report"
    )
    p_assemble.add_argument(
        "--input", required=True, help="Input merged-findings JSON path"
    )
    p_assemble.add_argument("--output", required=True, help="Output report JSON path")

    p_regenerate = sub.add_parser(
        "regenerate", help="Recompute derived fields in an existing report"
    )
    p_regenerate.add_argument("report", help="Report JSON path to update in place")

    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        return cmd_prepare(args)
    elif args.command == "assemble":
        return cmd_assemble(args)
    elif args.command == "regenerate":
        return cmd_regenerate(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
