#!/usr/bin/env python3
"""Build and post a GitHub PR review from a consolidated report.json.

Deterministic half of review posting: the caller (an LLM coordinator) supplies
only a one-line ``--body`` and an optional ``{final_id: comment text | null}``
map; this script selects the findings, maps each ``location`` onto the RIGHT
side of the PR diff, skips findings already raised in an open review thread,
routes off-diff findings into the review body (never dropping them), picks
APPROVE vs COMMENT, and posts with fallbacks.

Input must be an assembled report (``schema_version``, ``summary_statistics``
and ``findings`` sections whose findings carry final IDs); anything else exits 2.

Selection: severity >= ``--min-severity`` (default MEDIUM) or
``merge_class == "blocking"``; ``disputed`` findings are never posted and
``out_of_scope_follow_up`` ones go to the body, not inline. A ``null`` map
entry skips that finding. A finding counts as covered (listed in one body
line, not re-posted) only when an unresolved thread sits on an overlapping
current line of the same file and its first comment cites the finding's final
ID or exact title.

Event: APPROVE only when nothing is posted, no unresolved thread remains and no
non-disputed finding is blocking or MEDIUM+; otherwise COMMENT. ``--draft``
omits the event (pending review).

Limits: every comment and the body stay within GitHub's 65536 characters;
body entries that do not fit are named in an "N more finding(s)" line and
reported as ``omitted``. Posted text has @mentions (outside code) and HTML
comment openers neutralized.

Fallbacks: HTTP 422 with inline comments -> move them into the body and retry;
APPROVE rejected (403/422) -> retry as COMMENT. Only reads retry via ``ghsudo``.

Usage:
    python3 scripts/post_pr_review.py <owner/repo> <pr> <report.json> \\
        [--comments comments.json] [--body "One-line verdict."] \\
        [--min-severity MEDIUM] [--draft] [--commit SHA] [--dry-run]

Prints one JSON object: the review URL, event, and inline/in_body/omitted/
covered/skipped IDs (``--dry-run``: plus the payload; nothing is posted).

Exit codes: 0 posted (or dry run), 1 GitHub API failure, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from severity_util import SEV_LABELS, effective_severity, load_json_strict

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SEVERITY_BY_LABEL = {label: level for level, label in SEV_LABELS.items()}
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
_LOCATION_RE = re.compile(r":(\d+)(?:-(\d+))?(?::\d+)?$")  # optional :col
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN_RE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
_PARAGRAPH_BREAK_RE = re.compile(r"(\n[ \t]*\n)")
_MENTION_RE = re.compile(r"(?<!\w)@(?=[A-Za-z0-9])")
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_FILES_PER_PAGE = 100
_MAX_FILE_PAGES = 30  # the API lists at most 3000 files per PR
_MAX_THREAD_PAGES = 50
GITHUB_TEXT_LIMIT = 65536  # per review body and per review comment
_BODY_ITEM_LIMIT = 2000
_LEAD_LIMIT = 4000
_OMITTED_LINE_LIMIT = 4000
_DEFAULT_MIN_SEVERITY = SEVERITY_BY_LABEL["MEDIUM"]
_MAX_POST_ATTEMPTS = 3

_THREADS_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved path line startLine
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
            start = node.get("startLine") or end
            comments = node.get("comments", {}).get("nodes") or [{}]
            threads.append(
                OpenThread(
                    path=node.get("path") or "",
                    start=start,
                    end=end,
                    body=comments[0].get("body") or "",
                )
            )
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return threads


def _cites(body: str, phrase: str) -> bool:
    """True when ``phrase`` occurs in ``body`` as a whole, case-insensitive phrase."""
    words = phrase.split()
    if not words:
        return False
    pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
    return re.search(pattern, body, re.IGNORECASE) is not None


def is_covered(finding: dict[str, Any], threads: list[OpenThread]) -> bool:
    """True when an open thread already raises this very finding.

    Requires both an overlapping current line on the same file and a first
    comment citing the finding's final ID or its exact title.
    """
    path, start, end = _parse_location(finding.get("location", ""))
    if start is None or end is None:
        return False
    for thread in threads:
        if thread.path != path or thread.end is None:
            continue
        thread_start = thread.start or thread.end
        if not (start <= thread.end and thread_start <= end):
            continue
        if _cites(thread.body, str(finding.get("id", ""))) or _cites(
            thread.body, str(finding.get("title", ""))
        ):
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


def _holds_approval(finding: dict[str, Any]) -> bool:
    """A non-disputed finding that is blocking or at/above the default threshold.

    Such a finding forbids APPROVE even when unposted (null map entry, a raised
    ``--min-severity``): approval must not outrank what the report says.
    """
    merge_class = finding.get("merge_class")
    return merge_class != "disputed" and (
        merge_class == "blocking"
        or effective_severity(finding) >= _DEFAULT_MIN_SEVERITY
    )


def _heading(finding: dict[str, Any]) -> str:
    label = SEV_LABELS.get(effective_severity(finding), "?")
    blocking = " · BLOCKING" if finding.get("merge_class") == "blocking" else ""
    return f"**{finding.get('id', '?')}** · {label}{blocking}"


def _default_text(finding: dict[str, Any]) -> str:
    parts = [f"**{finding.get('title', '')}**", str(finding.get("description", ""))]
    if finding.get("recommendation"):
        parts.append(f"**Recommendation:** {finding['recommendation']}")
    return "\n\n".join(p for p in parts if p.strip())


def _next_fence(fence: Optional[str], line: str) -> Optional[str]:
    """Fence state after ``line``: the open fence's marker, or None outside one."""
    match = _FENCE_RE.match(line)
    if not match:
        return fence
    marker = match.group(1)
    if fence is None:
        return marker
    closes = marker[0] == fence[0] and len(marker) >= len(fence)
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
    fences = [m.group(1) for m in map(_FENCE_RE.match, text.splitlines()) if m]
    reserve = len(marker) + (1 + max(map(len, fences)) if fences else 0)
    cut = text[: max(limit - reserve, 0)]
    fence = _open_fence(cut)
    return cut + (f"\n{fence}" if fence else "") + marker


def _neutralize(text: str) -> str:
    text = _MENTION_RE.sub("@\u200b", text)
    return text.replace("<!--", "&lt;!--")


def _neutralize_prose(text: str) -> str:
    """Neutralize prose, leaving code spans (which never cross paragraphs) intact."""
    out: list[str] = []
    for paragraph in _PARAGRAPH_BREAK_RE.split(text):
        last = 0
        for match in _CODE_SPAN_RE.finditer(paragraph):
            out += [_neutralize(paragraph[last : match.start()]), match.group(0)]
            last = match.end()
        out.append(_neutralize(paragraph[last:]))
    return "".join(out)


def sanitize(text: str) -> str:
    """Stop posted text from pinging users or hiding content in an HTML comment.

    @mentions get a zero-width space and ``<!--`` is escaped — outside code
    spans and fenced blocks, where they are literal anyway. A fence left open
    is closed, so it cannot flip the fence state of text concatenated after it.
    """
    out: list[str] = []
    prose: list[str] = []
    fence: Optional[str] = None
    for line in text.splitlines(keepends=True):
        opened = fence is None
        fence = _next_fence(fence, line)
        if opened and fence is None:
            prose.append(line)
            continue
        if opened:
            out.append(_neutralize_prose("".join(prose)))
            prose = []
        out.append(line)
    out.append(_neutralize_prose("".join(prose)))
    if fence is not None:
        out.append(f"\n{fence}")
    return "".join(out)


@dataclass
class _Body:
    text: str
    posted: list[str]
    omitted: list[str]


def _render_body(
    body: str, inline: list[_Item], off_diff: list[_Item], covered: list[str]
) -> _Body:
    """Render the review body, packing off-diff items up to GitHub's limit."""
    lead = _clip(sanitize(body.strip()), _LEAD_LIMIT) or "Automated review."
    head = [lead, ""]
    if covered:
        head.append(
            _clip(
                f"Already raised in open threads: {', '.join(covered)}.",
                _BODY_ITEM_LIMIT,
            )
        )
    blocks = [
        "\n".join(
            [
                "",
                f"- {_heading(item.finding)} — "
                f"`{str(item.finding.get('location', '')).replace('`', '')}`",
                "",
                _clip(item.text, _BODY_ITEM_LIMIT),
            ]
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
            _clip(
                f"{len(omitted)} more finding(s) did not fit GitHub's size limit "
                f"— see the full report: {', '.join(omitted)}",
                _OMITTED_LINE_LIMIT,
            ),
        ]
    return _Body("\n".join(lines), posted, omitted)


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
        if finding.get("merge_class") == "disputed":
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
        text = sanitize(options.comments.get(fid) or _default_text(finding))
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
                "body": _clip(
                    f"{_heading(item.finding)}\n\n{item.text}", GITHUB_TEXT_LIMIT
                ),
            }
            for item in inline
            if item.anchor
        ],
    }
    if event is not None:
        payload["event"] = event
    return payload, body


def post_review(
    gh: Any, report: dict[str, Any], options: ReviewOptions, *, dry_run: bool = False
) -> PostResult:
    """Build the review from ``report`` and post it (unless ``dry_run``)."""
    held = any(_holds_approval(f) for f in validate_report(report))
    commit = (
        options.commit
        or gh.request("GET", f"repos/{options.repo}/pulls/{options.pr}")["head"]["sha"]
    )
    hunks = fetch_diff_hunks(gh, options.repo, options.pr)
    threads = fetch_open_threads(gh, options.repo, options.pr)
    inline, off_diff, covered, skipped = build_review(report, options, hunks, threads)

    event: Optional[str] = None
    if not options.draft:
        clean = not inline and not off_diff and not threads and not held
        event = "APPROVE" if clean else "COMMENT"

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
    parser.add_argument("--body", default="", help="One-line review verdict")
    parser.add_argument(
        "--min-severity",
        choices=list(SEVERITY_BY_LABEL),
        default="MEDIUM",
        help="Lowest band posted (blocking findings always are)",
    )
    parser.add_argument(
        "--draft", action="store_true", help="Create a pending (draft) review"
    )
    parser.add_argument("--commit", help="Commit SHA (default: PR head)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the payload, do not post"
    )
    return parser.parse_args(argv)


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
        validate_report(report)
        check_schema(report)
        options = ReviewOptions(
            repo=args.repo,
            pr=args.pr,
            body=args.body,
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

    try:
        result = post_review(GhCli(), report, options, dry_run=args.dry_run)
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
