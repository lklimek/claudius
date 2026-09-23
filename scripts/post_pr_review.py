#!/usr/bin/env python3
"""Build and post a GitHub PR review from a consolidated report.json.

Deterministic half of review posting: the caller (an LLM coordinator) supplies
only a one-line verdict (``--body`` or ``--body-file``) and an optional
``{final_id: comment text | null}`` map; this script selects the findings, maps
each ``location`` onto the RIGHT side of the PR diff, skips findings already
raised in an open review thread, routes off-diff findings into the review body
(never dropping them), picks APPROVE vs COMMENT, and posts with fallbacks.

Input must be an assembled report (``schema_version``, ``summary_statistics``
and ``findings`` sections whose findings carry final IDs), schema-valid, with
derived fields (stats, top findings, remediation) agreeing with the findings;
anything else exits 2. Each finding's ``severity``/``overall_severity`` must be
what its likelihood/impact floats derive (as assemble computes them).
``metadata.commit`` and an explicit ``--commit`` must match the current PR head.
The head is checked before and after fetching the diff and threads; posting uses
that SHA. ``metadata.base_commit``, when present, must equal the PR's current
merge-base (compare API, read after the diff and threads). A stale report or a
changed diff scope exits 2 and must be regenerated.

Selection: severity >= ``--min-severity`` (default MEDIUM) or
``merge_class == "blocking"``; ``disputed`` findings whose ``ai_verdict`` is
``false_positive``/``duplicate`` are never posted (any other ``disputed`` counts
as undisputed) and
``out_of_scope_follow_up`` ones go to the body, not inline. A ``null`` map
entry skips that finding. A finding counts as covered (listed in one body
line, not re-posted) only when an unresolved RIGHT-side thread overlaps a current
line of the same file and its first comment cites the finding's exact title as a
whole, case-insensitive phrase.

Event: APPROVE only with ``metadata.commit`` and a verified ``metadata.base_commit``,
when nothing is posted, no unresolved thread remains and no non-disputed finding
is blocking or MEDIUM+; otherwise COMMENT. ``--draft`` omits the event (pending
review). A missing ``commit``/``base_commit`` or an unreadable merge-base forces
COMMENT with a warning. Incomplete thread pagination fails without posting.

Limits: every comment and the body stay within GitHub's 65536 characters;
body entries that do not fit are named in an "N more finding(s)" line and
reported as ``omitted``. Each finding's one-line heading (ID, severity, title;
location in the body; each part capped) stays outside the clipped text. Posted
text is clipped first, then has @mentions and HTML comment openers neutralized
everywhere, code included.

Input safety: ``<owner/repo>`` must equal ``GITHUB_REPOSITORY`` when set, else
the cwd checkout's ``origin`` (case-insensitive). ``--body-file`` must be a
regular, non-symlink file under the cwd or the report's directory, outside any
``.git`` directory, ``/proc`` and ``/sys``. Any body, comment or finding text
that looks like a credential (GitHub/Anthropic token, ``x-access-token:``)
exits 2 before any GitHub call, without echoing it.

Fallbacks: HTTP 422 with inline comments -> move them into the body and retry;
APPROVE rejected (403/422) -> retry as COMMENT. Only reads retry via ``ghsudo``.

Usage:
    python3 scripts/post_pr_review.py <owner/repo> <pr> <report.json> \\
        [--comments comments.json] [--body "Verdict." | --body-file body.md] \\
        [--min-severity MEDIUM] [--draft] [--commit SHA] [--dry-run]

Prints one JSON object: the review URL, event, and inline/in_body/omitted/
covered/skipped IDs (``--dry-run``: plus the payload; nothing is posted).

Exit codes: 0 posted (or dry run), 1 GitHub API failure, 2 bad input.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from consolidate_reports import _derive_metadata_repository, regenerate_derived
from severity_util import (
    SEV_LABELS,
    derive_overall,
    derive_severity_int,
    effective_severity,
    load_json_strict,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SEVERITY_BY_LABEL = {label: level for level, label in SEV_LABELS.items()}
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
_LOCATION_RE = re.compile(r":(\d+)(?:-(\d+))?(?::\d+)?$")  # optional :col
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_WHITESPACE_RE = re.compile(r"\s+")
# Only an ASCII alphanumeric before "@" exempts it (an email): GitHub still
# links "_@user_" (emphasis) and "é@user" (non-ASCII is a non-word there).
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9])@(?=[A-Za-z0-9])")
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_FILES_PER_PAGE = 100
_MAX_FILE_PAGES = 30  # the API lists at most 3000 files per PR
_MAX_THREAD_PAGES = 50
GITHUB_TEXT_LIMIT = 65536  # per review body and per review comment
ATTRIBUTION = (
    "\n\n<sub>🤖 Co-authored by [Claudius the Magnificent]"
    "(https://github.com/lklimek/claudius) AI Agent</sub>"
)
_BODY_ITEM_LIMIT = 2000
_LEAD_LIMIT = 4000
_OMITTED_LINE_LIMIT = 4000
_HEADING_PART_LIMIT = 300  # per id/title/location; heading stays well under 1000
_DEFAULT_MIN_SEVERITY = SEVERITY_BY_LABEL["MEDIUM"]
_MAX_POST_ATTEMPTS = 3
# ai_verdict values that make a finding invalid (skills/severity § 5): only
# those let merge_class "disputed" exempt it from posting and from APPROVE.
_INVALID_VERDICTS = frozenset({"false_positive", "duplicate"})
_SECRET_PATTERNS = {
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "GitHub fine-grained token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "git credential URL": re.compile(r"x-access-token:", re.IGNORECASE),
}
_BODY_FILE_DENIED_ROOTS = (Path("/proc"), Path("/sys"))

_THREADS_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved path line startLine diffSide startDiffSide
          comments(first: 1) { nodes { body } }
        }
      }
    }
  }
}
"""

Hunk = tuple[int, int]


# ---------------------------------------------------------------------------
# gh adapter
# ---------------------------------------------------------------------------
class GhApiError(Exception):
    """A GitHub API call failed; ``status`` is the HTTP status when known."""

    def __init__(self, status: Optional[int], message: str) -> None:
        super().__init__(message)
        self.status = status


class GhCli:
    """Minimal ``gh api`` client; reads retry once via ``ghsudo`` on 403/404.

    Writes never escalate: a review (APPROVE above all) must come from the
    caller's own identity, not a maintainer's.
    """

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        which: Callable[[str], Optional[str]] = shutil.which,
    ) -> None:
        self._run = runner
        self._which = which

    def _invoke(self, prefix: list[str], args: list[str], stdin: Optional[str]):
        try:
            return self._run(
                [*prefix, "api", *args],
                input=stdin,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise GhApiError(None, f"{prefix[0]} CLI not found on PATH") from error

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        """Call ``gh api``; return parsed JSON or raise GhApiError."""
        args = ["--method", method, path]
        stdin = None
        if payload is not None:
            args += ["--input", "-"]
            stdin = json.dumps(payload)
        result = self._invoke(["gh"], args, stdin)
        if result.returncode != 0 and _is_read(method, path, payload):
            status = _http_status(result.stderr)
            if status in (403, 404) and self._which("ghsudo"):
                result = self._invoke(["ghsudo", "gh"], args, stdin)
        if result.returncode != 0:
            raise GhApiError(
                _http_status(result.stderr),
                (result.stderr.strip() + " " + result.stdout.strip()).strip(),
            )
        try:
            return json.loads(result.stdout) if result.stdout.strip() else None
        except ValueError as error:
            raise GhApiError(None, f"non-JSON response from gh api {path}") from error


def graphql(gh: Any, query: str, variables: dict[str, Any]) -> Any:
    """Run a GraphQL query via ``gh.request``; GraphQL errors raise GhApiError."""
    data = gh.request("POST", "graphql", {"query": query, "variables": variables})
    if not isinstance(data, dict) or data.get("errors"):
        errors = data.get("errors") if isinstance(data, dict) else data
        raise GhApiError(None, f"GraphQL error: {json.dumps(errors)}")
    return data


def _is_read(method: str, path: str, payload: Any) -> bool:
    """True for a GET or a GraphQL ``query`` (never a mutation)."""
    if method == "GET":
        return True
    query = payload.get("query") if isinstance(payload, dict) else None
    return (
        path == "graphql"
        and isinstance(query, str)
        and query.lstrip().startswith(("query", "{"))
    )


def _http_status(stderr: str) -> Optional[int]:
    match = _HTTP_STATUS_RE.search(stderr or "")
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Diff mapping
# ---------------------------------------------------------------------------
def parse_patch_hunks(patch: str) -> list[Hunk]:
    """Return inclusive RIGHT-side (new-file) line ranges of each diff hunk."""
    hunks: list[Hunk] = []
    for match in _HUNK_RE.finditer(patch or ""):
        start = int(match.group(1))
        length = int(match.group(2)) if match.group(2) is not None else 1
        if length > 0:
            hunks.append((start, start + length - 1))
    return hunks


def _parse_location(location: str) -> tuple[str, Optional[int], Optional[int]]:
    """Split ``path:start[-end][:col]`` into (normalized path, start, end)."""
    match = _LOCATION_RE.search(location or "")
    path = location[: match.start()] if match else (location or "")
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    if not match:
        return path, None, None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    return path, min(start, end), max(start, end)


def anchor_for(location: str, hunks: dict[str, list[Hunk]]) -> Optional[dict[str, Any]]:
    """Map a finding location onto a RIGHT-side diff anchor, or None if off-diff.

    A range is clamped to the first hunk it intersects: GitHub requires both
    ``start_line`` and ``line`` inside one hunk.
    """
    path, start, end = _parse_location(location)
    if start is None or end is None or path not in hunks:
        return None
    for hunk_start, hunk_end in hunks[path]:
        low, high = max(start, hunk_start), min(end, hunk_end)
        if low <= high:
            anchor: dict[str, Any] = {"path": path, "line": high, "side": "RIGHT"}
            if low < high:
                anchor.update(start_line=low, start_side="RIGHT")
            return anchor
    return None


# ---------------------------------------------------------------------------
# GitHub reads
# ---------------------------------------------------------------------------
def fetch_diff_hunks(gh: Any, repo: str, pr: int) -> dict[str, list[Hunk]]:
    """Return {path: hunks} for every PR file that has a textual patch."""
    hunks: dict[str, list[Hunk]] = {}
    for page in range(1, _MAX_FILE_PAGES + 1):
        files = gh.request(
            "GET",
            f"repos/{repo}/pulls/{pr}/files?per_page={_FILES_PER_PAGE}&page={page}",
        )
        for item in files or []:
            if isinstance(item, dict) and item.get("patch"):
                hunks[item["filename"]] = parse_patch_hunks(item["patch"])
        if not files or len(files) < _FILES_PER_PAGE:
            break
    return hunks


@dataclass(frozen=True)
class OpenThread:
    """An unresolved review thread's anchor and first comment."""

    path: str
    start: Optional[int]
    end: Optional[int]
    body: str
    diff_side: Optional[str]
    start_diff_side: Optional[str]


def fetch_open_threads(gh: Any, repo: str, pr: int) -> list[OpenThread]:
    """Return every unresolved review thread on the PR."""
    owner, name = repo.split("/", 1)
    threads: list[OpenThread] = []
    cursor = None
    for _ in range(_MAX_THREAD_PAGES):
        data = graphql(
            gh,
            _THREADS_QUERY,
            {"owner": owner, "repo": name, "pr": pr, "cursor": cursor},
        )
        conn = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in conn["nodes"]:
            if node.get("isResolved"):
                continue
            # Outdated threads have no current line; originalLine numbers an
            # older commit, so they never anchor coverage.
            end = node.get("line")
            start = node.get("startLine")
            comments = node.get("comments", {}).get("nodes") or [{}]
            threads.append(
                OpenThread(
                    path=node.get("path") or "",
                    start=start,
                    end=end,
                    body=comments[0].get("body") or "",
                    diff_side=node.get("diffSide"),
                    start_diff_side=node.get("startDiffSide"),
                )
            )
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    else:
        raise GhApiError(
            None, "Review thread pagination limit reached; refusing partial thread list"
        )
    return threads


def _cites(body: str, phrase: str) -> bool:
    """True when ``phrase`` occurs in ``body`` as a whole, case-insensitive phrase.

    Zero-width spaces are dropped from ``body`` first: sanitize() inserts them,
    so a comment this script posted must still cite its own finding's title.
    """
    words = phrase.split()
    if not words:
        return False
    pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
    return re.search(pattern, body.replace("\u200b", ""), re.IGNORECASE) is not None


def is_covered(finding: dict[str, Any], threads: list[OpenThread]) -> bool:
    """True when an open thread already raises this very finding.

    Requires an overlapping current RIGHT-side line on the same file and a first
    comment citing the finding's exact title as a whole, case-insensitive phrase.
    """
    path, start, end = _parse_location(finding.get("location", ""))
    if start is None or end is None:
        return False
    for thread in threads:
        if (
            thread.path != path
            or thread.end is None
            or thread.diff_side != "RIGHT"
            or (thread.start is not None and thread.start_diff_side != "RIGHT")
        ):
            continue
        thread_start = thread.start or thread.end
        if not (start <= thread.end and thread_start <= end):
            continue
        if _cites(thread.body, str(finding.get("title", ""))):
            return True
    return False


# ---------------------------------------------------------------------------
# Review construction
# ---------------------------------------------------------------------------
class ReportError(ValueError):
    """The input is not an assembled report.json."""


def validate_report(report: Any) -> list[dict[str, Any]]:
    """Return every finding of an assembled report, or raise ReportError.

    Guards against posting ``{}``, a typo'd key, intermediate.json or
    merged-findings.json: each would otherwise yield zero findings -> APPROVE.
    """
    if not isinstance(report, dict):
        raise ReportError("expected a report object")
    missing = [
        key
        for key, kind in (
            ("schema_version", str),
            ("summary_statistics", dict),
            ("findings", list),
        )
        if not isinstance(report.get(key), kind)
    ]
    if missing:
        raise ReportError(
            f"not an assembled report.json (missing/invalid: {', '.join(missing)})"
            " — pass finalize's report.json"
        )
    findings: list[dict[str, Any]] = []
    for index, section in enumerate(report["findings"]):
        if not isinstance(section, dict) or not isinstance(
            section.get("findings"), list
        ):
            raise ReportError(f"findings[{index}]: expected a section object")
        for finding in section["findings"]:
            fid = finding.get("id") if isinstance(finding, dict) else None
            if not isinstance(fid, str) or not fid.strip():
                raise ReportError(
                    f"findings[{index}]: every finding needs a final string id"
                )
            findings.append(finding)
    return findings


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
)


def check_schema(report: dict[str, Any]) -> None:
    """Raise ReportError unless ``report`` validates against the report schema.

    Fails closed: without jsonschema or the schema file, nothing can APPROVE.
    """
    try:
        import jsonschema
    except ImportError as error:
        raise ReportError("python3-jsonschema is required to validate") from error
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReportError(f"cannot load {SCHEMA_PATH}: {error}") from error
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(report), key=lambda e: [str(p) for p in e.absolute_path]
    )
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.absolute_path) or "(root)"
        raise ReportError(
            f"fails review-report schema ({len(errors)} error(s); first at "
            f"{where}: {first.message})"
        )


def check_derived(report: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Raise ReportError when a finding-derived field contradicts the findings.

    Recomputes every derived field on a copy (``regenerate_derived``): a report
    whose findings were lost while its stats, top findings or remediation still
    claim blockers must not reach APPROVE. ``summary_statistics`` must match
    exactly; ``top_findings``/``remediation`` may differ only as a curated
    override (finalize's ``*_override``) citing real findings faithfully.
    """
    expected = copy.deepcopy(report)
    regenerate_derived(expected)
    stats, want = report["summary_statistics"], expected["summary_statistics"]
    if "critical_count" in stats:  # legacy optional key, never regenerated
        want["critical_count"] = want["severity_counts"].get("CRITICAL", 0)
    stale = sorted(k for k in set(stats) | set(want) if stats.get(k) != want.get(k))
    if stale:
        raise ReportError(
            f"summary_statistics ({', '.join(stale)}) contradict the findings;"
            " re-run consolidate_reports.py finalize or regenerate"
        )
    for finding in findings:
        _check_severity_derivation(finding)
    by_id = {finding["id"]: finding for finding in findings}
    for entry in report.get("top_findings") or []:
        finding = by_id.get(entry.get("id"))
        if (
            finding is None
            or entry.get("severity") != effective_severity(finding)
            # merge_class is optional in a top_findings entry (curated override)
            or (
                "merge_class" in entry
                and entry["merge_class"] != finding.get("merge_class")
            )
        ):
            raise ReportError(
                f"top_findings entry {entry.get('id')!r} does not match a finding"
            )
    for bucket in report.get("remediation") or []:
        ids = bucket.get("finding_ids", [])
        unknown = [fid for fid in ids if fid not in by_id]
        if unknown or bucket.get("count") != len(ids):
            raise ReportError(
                f"remediation bucket {bucket.get('priority')!r} does not match "
                f"its findings (unknown: {unknown}, count: {bucket.get('count')})"
            )


def _check_severity_derivation(finding: dict[str, Any]) -> None:
    """Raise ReportError unless ``severity``/``overall_severity`` match the floats.

    APPROVE reads the floats while the rendered report shows ``severity``: a
    report claiming CRITICAL over INFO floats must not be approvable. Same
    derivation as consolidate_reports' assemble; absent fields cannot disagree.
    """
    overall = derive_overall(finding)
    if overall is None:  # schema requires both floats; effective_severity copes
        return
    stored = finding.get("overall_severity", overall)
    if (
        not isinstance(stored, (int, float))
        or isinstance(stored, bool)
        or not math.isclose(stored, overall, abs_tol=1e-9)
        or finding.get("severity", derive_severity_int(overall))
        != derive_severity_int(overall)
    ):
        raise ReportError(
            f"finding {finding.get('id')!r}: severity/overall_severity contradict "
            "its likelihood/impact; re-run consolidate_reports.py finalize"
        )


def _strings(value: Any):
    """Yield every string nested in ``value`` (dict values, list items)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _secret_kind(text: str) -> Optional[str]:
    """Name of the first credential pattern found in ``text``, or None."""
    for kind, pattern in _SECRET_PATTERNS.items():
        if pattern.search(text):
            return kind
    return None


def check_secrets(findings: list[dict[str, Any]], options: "ReviewOptions") -> None:
    """Raise ReportError if anything that could be posted looks like a credential.

    Scans the body, the comment map and every finding string (posted or not:
    fail closed). The error names where, never the match itself.
    """
    sources: list[tuple[str, Any]] = [("review body", options.body)]
    sources += [
        (f"comment for {fid!r}", text) for fid, text in options.comments.items()
    ]
    sources += [(f"finding {f.get('id')!r}", f) for f in findings]
    for where, value in sources:
        for text in _strings(value):
            kind = _secret_kind(text)
            if kind:
                raise ReportError(
                    f"{where} contains what looks like a {kind}; redact it, "
                    "nothing was posted"
                )


@dataclass
class ReviewOptions:
    """Caller-supplied review parameters."""

    repo: str
    pr: int
    body: str = ""
    comments: dict[str, Optional[str]] = field(default_factory=dict)
    min_severity: int = _DEFAULT_MIN_SEVERITY
    draft: bool = False
    commit: Optional[str] = None


@dataclass
class _Item:
    finding: dict[str, Any]
    text: str
    anchor: Optional[dict[str, Any]]

    @property
    def fid(self) -> str:
        return str(self.finding.get("id", "?"))


@dataclass
class PostResult:
    """What was (or would be) posted."""

    event: Optional[str]
    inline: list[str]
    in_body: list[str]
    omitted: list[str]
    covered: list[str]
    skipped: list[str]
    payload: dict[str, Any]
    url: Optional[str] = None

    def summary(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "event": self.event,
            "inline": self.inline,
            "in_body": self.in_body,
            "omitted": self.omitted,
            "covered_by_open_threads": self.covered,
            "skipped": self.skipped,
        }


def _iter_report_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(validate_report(report), key=lambda f: -effective_severity(f))


def _is_disputed(finding: dict[str, Any]) -> bool:
    """``disputed`` backed by an invalid-finding ``ai_verdict``; nothing else exempts."""
    return (
        finding.get("merge_class") == "disputed"
        and finding.get("ai_verdict") in _INVALID_VERDICTS
    )


def _holds_approval(finding: dict[str, Any]) -> bool:
    """A non-disputed finding that is blocking or at/above the default threshold.

    Such a finding forbids APPROVE even when unposted (null map entry, a raised
    ``--min-severity``): approval must not outrank what the report says.
    """
    return not _is_disputed(finding) and (
        finding.get("merge_class") == "blocking"
        or effective_severity(finding) >= _DEFAULT_MIN_SEVERITY
    )


def _one_line(value: Any) -> str:
    """Collapse every whitespace run to one space: no line can start a block."""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def _short(value: Any, limit: int = _HEADING_PART_LIMIT) -> str:
    """One line of at most ``limit`` characters."""
    text = _one_line(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _heading(finding: dict[str, Any], *, with_location: bool = False) -> str:
    """One line naming the finding: ID, severity, title (and location).

    Kept outside the clipped text, so a posted finding is always identifiable.
    """
    label = SEV_LABELS.get(effective_severity(finding), "?")
    blocking = " · BLOCKING" if finding.get("merge_class") == "blocking" else ""
    parts = [f"**{_short(finding.get('id', '?'))}** · {label}{blocking}"]
    title = _short(finding.get("title", ""))
    if title:
        parts.append(f"**{title}**")
    if with_location:
        parts.append(f"`{_short(finding.get('location', '')).replace('`', '')}`")
    return " — ".join(parts)


def _default_text(finding: dict[str, Any]) -> str:
    parts = [str(finding.get("description", ""))]
    if finding.get("recommendation"):
        parts.append(f"**Recommendation:** {finding['recommendation']}")
    return "\n\n".join(p for p in parts if p.strip())


def _next_fence(fence: Optional[str], line: str) -> Optional[str]:
    """Fence state after ``line``: the open fence's marker, or None outside one."""
    match = _FENCE_RE.match(line)
    if not match:
        return fence
    marker = match.group(1)
    tail = line[match.end() :]
    if fence is None:
        if marker[0] == "`" and "`" in tail:
            return None
        return marker
    closes = (
        marker[0] == fence[0]
        and len(marker) >= len(fence)
        and not tail.strip(" \t\r\n")
    )
    return None if closes else fence


def _open_fence(text: str) -> Optional[str]:
    """Return the marker of a code fence left open at the end of ``text``."""
    fence: Optional[str] = None
    for line in text.splitlines():
        fence = _next_fence(fence, line)
    return fence


def _clip(text: str, limit: int) -> str:
    """Truncate to ``limit`` characters with a visible marker, closing any open fence."""
    if len(text) <= limit:
        return text
    marker = "\n\n…(truncated)"
    room = max(limit - len(marker), 0)
    cut = text[:room]
    # Reserve room to close only the fence the kept prefix leaves open; shrinking
    # strictly shortens ``cut`` (the closer is non-empty), so this terminates.
    while (fence := _open_fence(cut)) and len(cut) + 1 + len(fence) > room:
        cut = cut[: max(room - 1 - len(fence), 0)]
    return cut + (f"\n{fence}" if fence else "") + marker


_HTML_OPEN_RE = re.compile(r"<(?=[A-Za-z/!?])")
# "@" spelled as a character reference; a numeric one may omit its ";" when no
# further digit follows (HTML5 legacy parsing).
_ENTITY_AT_RE = re.compile(
    r"&(?:#0*64(?:;|(?![0-9]))|#x0*40(?:;|(?![0-9a-f]))|commat;)(?=[A-Za-z0-9])",
    re.IGNORECASE,
)


def _neutralize(line: str) -> str:
    """Break @mentions (literal or entity) and raw HTML with a zero-width space.

    A ``<`` followed by a zero-width space cannot start an HTML tag, so report
    text can neither hide later findings (``<!--``, ``<details>``) nor inject
    markup. Idempotent: the inserted character stops a second match.
    """
    line = _ENTITY_AT_RE.sub(lambda m: m.group(0) + "\u200b", line)
    return _HTML_OPEN_RE.sub("<\u200b", _MENTION_RE.sub("@\u200b", line))


def sanitize(text: str) -> str:
    """Stop posted text from pinging users or hiding content in an HTML comment.

    Every line is neutralized, code included: span, fence and HTML-block
    detection can all be fooled, so nothing is exempt. Fences are still tracked
    so one left open is closed and cannot swallow text concatenated after it.
    Idempotent, so already-sanitized fragments can be re-sanitized once composed.
    """
    out: list[str] = []
    fence: Optional[str] = None
    for line in text.splitlines(keepends=True):
        fence = _next_fence(fence, line)
        out.append(_neutralize(line))
    if fence is not None:
        out.append(f"\n{fence}")
    return "".join(out)


def _fit(text: str, limit: int) -> str:
    """Clip ``text``, then sanitize it, so the FINAL text fits ``limit`` characters.

    Sanitizing last means a clip can never cut a neutralized construct back open;
    zero-width insertions lengthen the text, so the clip budget shrinks until
    the sanitized result fits.
    """
    budget = limit
    while True:
        out = sanitize(_clip(text, budget))
        if len(out) <= limit or budget <= 0:
            return out
        budget -= len(out) - limit


def _compose(heading: str, text: str, limit: int) -> str:
    """Sanitized ``heading`` kept whole, then ``text`` fitted into what remains."""
    head = sanitize(heading)
    if not text.strip():
        return head
    return f"{head}\n\n{_fit(text, max(limit - len(head) - 2, 0))}"


@dataclass
class _Body:
    text: str
    posted: list[str]
    omitted: list[str]


def _render_body(
    body: str, inline: list[_Item], off_diff: list[_Item], covered: list[str]
) -> _Body:
    """Render the review body, packing off-diff items up to GitHub's limit."""
    lead = _fit(body.strip(), _LEAD_LIMIT) or "Automated review."
    head = [lead, ""]
    if covered:
        head.append(
            _fit(
                f"Already raised in open threads: {_one_line(', '.join(covered))}.",
                _BODY_ITEM_LIMIT,
            )
        )
    blocks = [
        "\n"
        + _compose(
            f"- {_heading(item.finding, with_location=True)}",
            item.text,
            _BODY_ITEM_LIMIT - 1,
        )
        for item in off_diff
    ]
    budget = GITHUB_TEXT_LIMIT - _OMITTED_LINE_LIMIT - 500  # 500: count line etc.
    budget -= len("\n".join(head))
    packed: list[int] = []
    for index, block in enumerate(blocks):
        if len(block) + 1 > budget:
            break
        budget -= len(block) + 1
        packed.append(index)
    posted = [off_diff[i].fid for i in packed]
    omitted = [item.fid for item in off_diff[len(packed) :]]
    lines = [
        *head,
        f"{len(inline) + len(posted)} finding(s) posted: {len(inline)} inline, "
        f"{len(posted)} in this body.",
    ]
    if posted:
        lines += ["", "### Findings outside the diff or deferred"]
        lines += [blocks[i] for i in packed]
    if omitted:
        lines += [
            "",
            _fit(
                f"{len(omitted)} more finding(s) did not fit GitHub's size limit "
                f"— see the full report: {_one_line(', '.join(omitted))}",
                _OMITTED_LINE_LIMIT,
            ),
        ]
    # Safety net: every fragment is already sanitized, so this is a no-op unless
    # composition somehow re-opened a construct. The trusted footer is appended
    # after sanitizing, so its markup survives.
    text = _fit("\n".join(lines), GITHUB_TEXT_LIMIT - len(ATTRIBUTION))
    return _Body(text + ATTRIBUTION, posted, omitted)


def build_review(
    report: dict[str, Any],
    options: ReviewOptions,
    hunks: dict[str, list[Hunk]],
    threads: list[OpenThread],
) -> tuple[list[_Item], list[_Item], list[str], list[str]]:
    """Select findings; return (inline, off_diff, covered IDs, skipped IDs)."""
    inline: list[_Item] = []
    off_diff: list[_Item] = []
    covered: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for finding in _iter_report_findings(report):
        fid = str(finding.get("id", "?"))
        seen.add(fid)
        if _is_disputed(finding):
            continue
        if (
            effective_severity(finding) < options.min_severity
            and finding.get("merge_class") != "blocking"
        ):
            continue
        if fid in options.comments and options.comments[fid] is None:
            skipped.append(fid)
            continue
        if is_covered(finding, threads):
            covered.append(fid)
            continue
        text = options.comments.get(fid) or _default_text(finding)
        # Deferred follow-ups are listed, not anchored: they are not asks on this diff.
        anchor = (
            None
            if finding.get("merge_class") == "out_of_scope_follow_up"
            else anchor_for(finding.get("location", ""), hunks)
        )
        item = _Item(finding, text, anchor)
        (inline if item.anchor else off_diff).append(item)
    unknown = sorted(set(options.comments) - seen)
    if unknown:
        log.warning("Comment map IDs not in the report (ignored): %s", unknown)
    return inline, off_diff, covered, skipped


def _payload(
    options: ReviewOptions,
    commit: str,
    event: Optional[str],
    inline: list[_Item],
    off_diff: list[_Item],
    covered: list[str],
) -> tuple[dict[str, Any], _Body]:
    body = _render_body(options.body, inline, off_diff, covered)
    payload: dict[str, Any] = {
        "commit_id": commit,
        "body": body.text,
        "comments": [
            {
                **item.anchor,
                "body": _compose(_heading(item.finding), item.text, GITHUB_TEXT_LIMIT),
            }
            for item in inline
            if item.anchor
        ],
    }
    if event is not None:
        payload["event"] = event
    return payload, body


def verify_diff_scope(
    gh: Any, repo: str, pr: dict[str, Any], reviewed_base: str
) -> bool:
    """True when ``reviewed_base`` is the PR's current merge-base.

    A retargeted or rebased base changes the diff GitHub reviews, so a mismatch
    raises ReportError. A failed or malformed compare read only returns False
    (no APPROVE): it must not stop a COMMENT from posting.
    """
    try:
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        data = gh.request("GET", f"repos/{repo}/compare/{base}...{head}?per_page=1")
        current = data["merge_base_commit"]["sha"]
    except (GhApiError, KeyError, TypeError) as error:
        log.warning("Cannot read the PR merge-base (%s); using COMMENT", error)
        return False
    if not isinstance(current, str):
        log.warning("Malformed PR merge-base %r; using COMMENT", current)
        return False
    if current != reviewed_base:
        raise ReportError(
            f"reviewed diff scope changed: merge-base was {reviewed_base}, "
            f"is {current}; re-run the review"
        )
    return True


def post_review(
    gh: Any, report: dict[str, Any], options: ReviewOptions, *, dry_run: bool = False
) -> PostResult:
    """Build the review from ``report`` and post it (unless ``dry_run``)."""
    findings = validate_report(report)
    check_secrets(findings, options)
    held = any(_holds_approval(f) for f in findings)
    pr_path = f"repos/{options.repo}/pulls/{options.pr}"
    head = gh.request("GET", pr_path)["head"]["sha"]
    metadata = report.get("metadata", {})
    reviewed = metadata.get("commit")
    reviewed_base = metadata.get("base_commit")
    if reviewed and reviewed != head:
        raise ReportError(
            f"report is for {reviewed}, PR head is {head}; re-run the review"
        )
    if options.commit and reviewed and options.commit != reviewed:
        raise ReportError("--commit must equal metadata.commit")
    commit = reviewed or options.commit or head
    if commit != head:
        raise ReportError(f"--commit is {commit}, PR head is {head}; re-run the review")
    hunks = fetch_diff_hunks(gh, options.repo, options.pr)
    threads = fetch_open_threads(gh, options.repo, options.pr)
    pr = gh.request("GET", pr_path)
    current_head = pr["head"]["sha"]
    if current_head != commit:
        raise ReportError(
            f"PR head changed from {commit} to {current_head}; re-run the review"
        )
    scope_verified = reviewed_base is not None and verify_diff_scope(
        gh, options.repo, pr, reviewed_base
    )
    inline, off_diff, covered, skipped = build_review(report, options, hunks, threads)

    event: Optional[str] = None
    if not options.draft:
        clean = not inline and not off_diff and not threads and not held
        event = "APPROVE" if clean and reviewed and scope_verified else "COMMENT"
        if not reviewed:
            log.warning("No metadata.commit: cannot APPROVE; using COMMENT")
        if not reviewed_base:
            log.warning("No metadata.base_commit: cannot APPROVE; using COMMENT")

    def result(url: Optional[str] = None) -> PostResult:
        payload, body = _payload(options, commit, event, inline, off_diff, covered)
        return PostResult(
            event=event,
            inline=[i.fid for i in inline],
            in_body=body.posted,
            omitted=body.omitted,
            covered=covered,
            skipped=skipped,
            payload=payload,
            url=url,
        )

    if dry_run:
        return result()

    path = f"repos/{options.repo}/pulls/{options.pr}/reviews"
    for attempt in range(1, _MAX_POST_ATTEMPTS + 1):
        payload, _body = _payload(options, commit, event, inline, off_diff, covered)
        try:
            response = gh.request("POST", path, payload)
            return result((response or {}).get("html_url"))
        except GhApiError as error:
            if attempt == _MAX_POST_ATTEMPTS:
                raise
            if event == "APPROVE" and error.status in (403, 422):
                log.warning("APPROVE rejected (%s); retrying as COMMENT", error)
                event = "COMMENT"
            elif error.status == 422 and inline:
                log.warning(
                    "Inline comments rejected (%s); moving %d into the body",
                    error,
                    len(inline),
                )
                off_diff = off_diff + inline
                inline = []
            else:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _repo_arg(value: str) -> str:
    if not _REPO_RE.match(value):
        raise argparse.ArgumentTypeError("expected owner/repo")
    return value


def _pr_arg(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("expected a positive PR number")
    return int(value)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Post a GitHub PR review built from a consolidated report.json."
    )
    parser.add_argument("repo", type=_repo_arg, help="owner/repo")
    parser.add_argument("pr", type=_pr_arg, help="Pull request number")
    parser.add_argument("report", type=Path, help="Consolidated report.json")
    parser.add_argument(
        "--comments",
        type=Path,
        help="JSON {final_id: comment text | null}; null skips the finding",
    )
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body", default="", help="One-line review verdict")
    body.add_argument(
        "--body-file",
        type=Path,
        help="Read the verdict from a UTF-8 file (safe for $ and backticks)",
    )
    parser.add_argument(
        "--min-severity",
        choices=list(SEVERITY_BY_LABEL),
        default="MEDIUM",
        help="Lowest band posted (blocking findings always are)",
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create a pending (draft) review"
    )
    parser.add_argument("--commit", help="Commit SHA (must match report and PR head)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the payload, do not post"
    )
    return parser.parse_args(argv)


def _read_body_file(path: Path, report: Path) -> str:
    """Read ``--body-file``, confined so it cannot publish credentials or state.

    Only a regular, non-symlink file under the cwd or the report's directory,
    outside any ``.git`` directory and ``/proc``/``/sys``: an argument such as
    ``.git/config`` (token-bearing remote URL) or ``/proc/self/environ`` must
    not become a public review body.
    """
    if path.is_symlink():
        raise ValueError(f"--body-file {path}: symlinks are refused")
    resolved = path.resolve(strict=True)
    roots = (Path.cwd().resolve(), report.resolve().parent)
    if (
        ".git" in resolved.parts
        or any(resolved.is_relative_to(d) for d in _BODY_FILE_DENIED_ROOTS)
        or not any(resolved.is_relative_to(r) for r in roots)
    ):
        raise ValueError(
            f"--body-file {path}: must be under the cwd or the report's directory,"
            " outside .git, /proc and /sys"
        )
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"--body-file {path}: not a regular file")
        return handle.read()


def _expected_repo() -> Optional[str]:
    """The only repo this run may post to: ``GITHUB_REPOSITORY``, else ``origin``."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    origin = _derive_metadata_repository(os.getcwd())
    return f"{origin['owner']}/{origin['repo']}" if origin else None


def _load_comments(path: Optional[Path]) -> dict[str, Optional[str]]:
    if path is None:
        return {}
    data = load_json_strict(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and (v is None or isinstance(v, str))
        for k, v in data.items()
    ):
        raise ValueError(f"{path}: expected an object of {{final_id: text | null}}")
    return data


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI."""
    args = parse_args(argv)
    try:
        report = load_json_strict(args.report.read_text(encoding="utf-8"))
        findings = validate_report(report)
        check_schema(report)
        check_derived(report, findings)
        options = ReviewOptions(
            repo=args.repo,
            pr=args.pr,
            body=(
                _read_body_file(args.body_file, args.report)
                if args.body_file
                else args.body
            ),
            comments=_load_comments(args.comments),
            min_severity=SEVERITY_BY_LABEL[args.min_severity],
            draft=args.draft,
            commit=args.commit,
        )
    except ReportError as error:
        log.error("%s: %s", args.report, error)
        return 2
    except (OSError, ValueError) as error:
        log.error("%s", error)
        return 2
    expected = _expected_repo()
    if expected is None or expected.casefold() != args.repo.casefold():
        log.error(
            "refusing to post to %s: this checkout is %s (GITHUB_REPOSITORY or origin)",
            args.repo,
            expected or "unknown",
        )
        return 2

    try:
        result = post_review(GhCli(), report, options, dry_run=args.dry_run)
    except ReportError as error:
        log.error("%s", error)
        return 2
    except GhApiError as error:
        log.error("GitHub API failure (HTTP %s): %s", error.status, error)
        return 1

    output = result.summary()
    if args.dry_run:
        output["payload"] = result.payload
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
