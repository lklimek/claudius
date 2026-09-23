"""Tests for post_pr_review.py — no network: the gh layer is faked."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import post_pr_review as ppr  # noqa: E402

HEAD = "a" * 40
BASE_TIP = "c" * 40
MERGE_BASE = "d" * 40

VALID_REPORT = Path(__file__).parent / "fixtures" / "reports" / "v4-minimal.json"

PATCH_A = "@@ -1,3 +10,5 @@ def f():\n ctx\n+add\n+add\n ctx\n ctx\n@@ -40,2 +50,2 @@\n x\n+y\n"


def _finding(fid: str, sev: int, location: str, **extra: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": fid,
        "severity": sev,
        "title": f"Title {fid}",
        "location": location,
        "description": f"Description {fid}.",
        "recommendation": f"Recommendation {fid}.",
        "merge_class": "non_blocking",
    }
    finding.update(extra)
    return finding


def _report(*findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "4.0.0",
        "metadata": {"commit": HEAD, "base_commit": MERGE_BASE},
        "summary_statistics": {"total_findings": len(findings)},
        "findings": [
            {"title": "S", "category": "security", "findings": list(findings)}
        ],
    }


def _valid_report(*findings: dict[str, Any]) -> dict[str, Any]:
    """Schema-valid report (the CLI validates) holding ``findings``."""
    report = json.loads(VALID_REPORT.read_text())
    floats = {"likelihood": 0.6, "impact": 0.6, "relevance": 0.5}
    report["findings"][0]["findings"] = [{**floats, **f} for f in findings]
    report["summary_statistics"]["total_findings"] = len(findings)
    return report


class FakeGh:
    """Records requests and replays canned responses per (method, path prefix)."""

    def __init__(
        self,
        *,
        files: list[dict[str, Any]] | None = None,
        threads: list[dict[str, Any]] | None = None,
        post_errors: list[ppr.GhApiError] | None = None,
        merge_bases: dict[str, Any] | None = None,
    ) -> None:
        self.files = (
            files if files is not None else [{"filename": "src/a.py", "patch": PATCH_A}]
        )
        self.threads = threads or []
        self.post_errors = list(post_errors or [])
        # base.sha -> merge-base SHA, or a GhApiError to raise, or None (no field)
        self.merge_bases = merge_bases or {BASE_TIP: MERGE_BASE}
        self.base_tip = BASE_TIP
        self.posted: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        self.calls.append((method, path))
        if path == "graphql":
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": self.threads,
                            }
                        }
                    }
                }
            }
        if path.endswith("/reviews") and method == "POST":
            self.posted.append(json.loads(json.dumps(payload)))
            if self.post_errors:
                raise self.post_errors.pop(0)
            return {"html_url": "https://github.com/o/r/pull/7#pullrequestreview-1"}
        if "/files" in path:
            page = int(path.rsplit("page=", 1)[1])
            return self.files if page == 1 else []
        if path.startswith("repos/o/r/compare/"):
            base, rest = path[len("repos/o/r/compare/") :].split("...", 1)
            assert rest == f"{HEAD}?per_page=1", path
            merge_base = self.merge_bases[base]
            if isinstance(merge_base, Exception):
                raise merge_base
            return (
                {} if merge_base is None else {"merge_base_commit": {"sha": merge_base}}
            )
        if path.startswith("repos/o/r/pulls/7"):
            return {"head": {"sha": HEAD}, "base": {"sha": self.base_tip}}
        raise AssertionError(f"unexpected request {method} {path}")


def _thread(path: str, line: int | None, body: str, resolved: bool = False, **kw: Any):
    node = {
        "isResolved": resolved,
        "path": path,
        "line": line,
        "startLine": kw.get("start"),
        "diffSide": kw.get("side", "RIGHT"),
        "startDiffSide": kw.get("start_side", "RIGHT" if kw.get("start") else None),
        "originalLine": kw.get("original"),
        "originalStartLine": None,
        "comments": {"nodes": [{"body": body}]},
    }
    return node


def _run(report: dict[str, Any], gh: FakeGh, **kw: Any) -> ppr.PostResult:
    options = ppr.ReviewOptions(
        repo="o/r",
        pr=7,
        body=kw.pop("body", "Grumpy verdict."),
        comments=kw.pop("comments", {}),
        min_severity=kw.pop("min_severity", 3),
        draft=kw.pop("draft", False),
        commit=kw.pop("commit", None),
    )
    return ppr.post_review(gh, report, options, dry_run=kw.pop("dry_run", False))


# ---------------------------------------------------------------------------
# diff mapping
# ---------------------------------------------------------------------------
class TestHunks:
    def test_parse_patch_right_side_ranges(self):
        assert ppr.parse_patch_hunks(PATCH_A) == [(10, 14), (50, 51)]

    def test_hunk_without_length_is_one_line_and_pure_deletion_is_skipped(self):
        patch = "@@ -3 +3 @@\n-a\n+b\n@@ -9,2 +8,0 @@\n-x\n-y\n"
        assert ppr.parse_patch_hunks(patch) == [(3, 3)]

    @pytest.mark.parametrize(
        ("location", "anchor"),
        [
            ("src/a.py:12", {"line": 12}),
            ("src/a.py:11-13", {"start_line": 11, "line": 13}),
            ("src/a.py:8-11", {"start_line": 10, "line": 11}),  # clamped into hunk
            ("src/a.py:14-60", {"line": 14}),  # first hunk hit, clamped to one line
            ("./src/a.py:50", {"line": 50}),
            ("src/a.py:11:5", {"line": 11}),  # path:line:col
        ],
    )
    def test_anchor_in_diff(self, location, anchor):
        hunks = {"src/a.py": ppr.parse_patch_hunks(PATCH_A)}
        got = ppr.anchor_for(location, hunks)
        expected = {"path": "src/a.py", "side": "RIGHT", **anchor}
        if "start_line" in anchor:
            expected["start_side"] = "RIGHT"
        assert got == expected

    @pytest.mark.parametrize(
        "location", ["src/a.py:30", "src/a.py", "src/other.py:10", "PR-body", ""]
    )
    def test_anchor_off_diff(self, location):
        assert ppr.anchor_for(location, {"src/a.py": [(10, 14)]}) is None


# ---------------------------------------------------------------------------
# selection, coverage, event choice
# ---------------------------------------------------------------------------
class TestBuildAndPost:
    def test_medium_plus_inline_and_off_diff_in_body(self):
        report = _report(
            _finding("SEC-001", 4, "src/a.py:11-12"),
            _finding("SEC-002", 3, "src/a.py:30"),  # off-diff
            _finding("SEC-003", 2, "src/a.py:11"),  # LOW, not blocking
            _finding("SEC-004", 1, "src/a.py:11"),  # INFO
        )
        gh = FakeGh()
        result = _run(report, gh, comments={"SEC-001": "Custom text."})
        [payload] = gh.posted
        assert payload["commit_id"] == HEAD
        assert payload["event"] == "COMMENT"
        [comment] = payload["comments"]
        assert comment["path"] == "src/a.py"
        assert comment["start_line"] == 11 and comment["line"] == 12
        assert "SEC-001" in comment["body"] and "Custom text." in comment["body"]
        assert "SEC-002" in payload["body"] and "src/a.py:30" in payload["body"]
        assert "Recommendation SEC-002." in payload["body"]
        assert "SEC-003" not in json.dumps(payload)
        assert "SEC-004" not in json.dumps(payload)
        assert payload["body"].startswith("Grumpy verdict.")
        assert result.inline == ["SEC-001"] and result.in_body == ["SEC-002"]

    def test_default_comment_text_uses_report_fields(self):
        gh = FakeGh()
        _run(_report(_finding("SEC-001", 3, "src/a.py:12")), gh)
        body = gh.posted[0]["comments"][0]["body"]
        assert "Title SEC-001" in body
        assert "Description SEC-001." in body
        assert "Recommendation SEC-001." in body

    def test_blocking_low_is_posted_and_disputed_high_is_not(self):
        report = _report(
            _finding("SEC-001", 2, "src/a.py:12", merge_class="blocking"),
            _finding("SEC-002", 4, "src/a.py:13", merge_class="disputed"),
        )
        gh = FakeGh()
        _run(report, gh)
        payload = json.dumps(gh.posted[0])
        assert "SEC-001" in payload and "BLOCKING" in payload
        assert "SEC-002" not in payload

    def test_out_of_scope_follow_up_goes_to_body_not_inline(self):
        report = _report(
            _finding("SEC-001", 4, "src/a.py:12", merge_class="out_of_scope_follow_up")
        )
        gh = FakeGh()
        result = _run(report, gh)
        assert gh.posted[0]["comments"] == []
        assert "SEC-001" in gh.posted[0]["body"]
        assert result.in_body == ["SEC-001"]

    def test_null_comment_entry_skips_finding(self):
        report = _report(_finding("SEC-001", 4, "src/a.py:12"))
        gh = FakeGh()
        result = _run(report, gh, comments={"SEC-001": None})
        assert gh.posted[0]["comments"] == []
        assert result.skipped == ["SEC-001"]

    def test_thread_citing_exact_title_on_overlapping_line_covers(self):
        report = _report(
            _finding("SEC-001", 4, "src/a.py:11-12"),
            _finding("SEC-002", 4, "src/a.py:50", title="Unchecked parser error"),
            _finding("SEC-003", 4, "src/a.py:13"),  # only a resolved thread here
        )
        threads = [
            _thread("src/a.py", 12, "**SEC-001** · HIGH\n\nTitle SEC-001"),
            _thread("src/a.py", 51, "Re: unchecked parser error.", start=50),
            _thread("src/a.py", 13, "Title SEC-003", resolved=True),
        ]
        gh = FakeGh(threads=threads)
        result = _run(report, gh)
        assert result.covered == ["SEC-001", "SEC-002"]
        assert [c["line"] for c in gh.posted[0]["comments"]] == [13]
        assert "SEC-001" in gh.posted[0]["body"]  # one-line mention
        assert gh.posted[0]["event"] == "COMMENT"

    def test_reassigned_id_alone_does_not_cover(self):
        thread = _thread("src/a.py", 11, "**SEC-001** · HIGH\n\nOld unrelated title")
        report = _report(_finding("SEC-001", 4, "src/a.py:11", title="New issue"))
        result = _run(report, FakeGh(threads=[thread]))
        assert result.covered == []
        assert result.inline == ["SEC-001"]

    @pytest.mark.parametrize(
        ("side", "start_side", "start", "covered"),
        [
            ("LEFT", None, None, False),
            ("LEFT", "LEFT", 10, False),
            ("RIGHT", "LEFT", 10, False),
            (None, None, None, False),
            ("RIGHT", "RIGHT", 10, True),
            ("RIGHT", None, None, True),
        ],
    )
    def test_coverage_requires_right_side_thread(
        self, side, start_side, start, covered
    ):
        thread = _thread(
            "src/a.py",
            12,
            "Title SEC-001",
            side=side,
            start_side=start_side,
            start=start,
        )
        result = _run(
            _report(_finding("SEC-001", 4, "src/a.py:12")), FakeGh(threads=[thread])
        )
        assert result.covered == (["SEC-001"] if covered else [])
        assert result.inline == ([] if covered else ["SEC-001"])

    def test_thread_query_fetches_and_retains_diff_sides(self):
        class QueryGh(FakeGh):
            def request(self, method, path, payload=None):
                if path == "graphql":
                    assert "diffSide" in payload["query"]
                    assert "startDiffSide" in payload["query"]
                return super().request(method, path, payload)

        gh = QueryGh(
            threads=[
                _thread(
                    "src/a.py", 12, "Title", side="LEFT", start=10, start_side="LEFT"
                )
            ]
        )
        [thread] = ppr.fetch_open_threads(gh, "o/r", 7)
        assert thread.diff_side == "LEFT"
        assert thread.start_diff_side == "LEFT"

    def test_exact_title_on_other_path_does_not_cover(self):
        thread = _thread("src/other.py", 11, "Title SEC-001")
        result = _run(
            _report(_finding("SEC-001", 4, "src/a.py:11")), FakeGh(threads=[thread])
        )
        assert result.covered == []
        assert result.inline == ["SEC-001"]

    def test_unrelated_thread_on_overlapping_lines_does_not_cover(self):
        thread = _thread("src/a.py", 14, "nit: typo in variable name", start=10)
        report = _report(
            _finding("SEC-001", 5, "src/a.py:12", title="SQL injection in f()")
        )
        result = _run(report, FakeGh(threads=[thread]))
        assert result.inline == ["SEC-001"] and result.covered == []

    def test_outdated_thread_never_covers(self):
        thread = _thread("src/a.py", None, "SEC-002: Auth bypass", original=12)
        report = _report(_finding("SEC-002", 5, "src/a.py:12", title="Auth bypass"))
        result = _run(report, FakeGh(threads=[thread]))
        assert result.inline == ["SEC-002"] and result.covered == []

    def test_title_must_match_as_whole_phrase(self):
        thread = _thread("src/a.py", 11, "This leaks memory, please fix.")
        report = _report(_finding("QA-003", 4, "src/a.py:11", title="Leak"))
        result = _run(report, FakeGh(threads=[thread]))
        assert result.inline == ["QA-003"]

    def test_id_prefix_of_longer_id_does_not_cover(self):
        thread = _thread("src/a.py", 11, "See SEC-0012 instead.")
        result = _run(
            _report(_finding("SEC-001", 4, "src/a.py:11")), FakeGh(threads=[thread])
        )
        assert result.covered == []

    def test_thread_on_other_lines_does_not_cover(self):
        thread = _thread("src/a.py", 50, "Title SEC-001")
        result = _run(
            _report(_finding("SEC-001", 4, "src/a.py:11")), FakeGh(threads=[thread])
        )
        assert result.covered == []

    def test_clean_review_approves(self):
        gh = FakeGh()
        result = _run(_report(_finding("SEC-001", 2, "src/a.py:12")), gh)
        assert gh.posted[0]["event"] == "APPROVE"
        assert gh.posted[0]["comments"] == []
        assert gh.posted[0]["body"].strip()
        assert result.event == "APPROVE"

    def test_unresolved_thread_prevents_approval(self):
        gh = FakeGh(threads=[_thread("src/z.py", 3, "still broken")])
        _run(_report(), gh)
        assert gh.posted[0]["event"] == "COMMENT"

    def test_draft_omits_event(self):
        gh = FakeGh()
        _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh, draft=True)
        assert "event" not in gh.posted[0]

    def test_explicit_commit_checks_pr_head(self):
        gh = FakeGh()
        _run(_report(), gh, commit=HEAD)
        assert gh.posted[0]["commit_id"] == HEAD
        assert ("GET", "repos/o/r/pulls/7") in gh.calls

    def test_file_without_patch_sends_findings_to_body(self):
        gh = FakeGh(files=[{"filename": "src/a.py"}])
        _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh)
        assert gh.posted[0]["comments"] == []
        assert "SEC-001" in gh.posted[0]["body"]

    def test_dry_run_does_not_post(self):
        gh = FakeGh()
        result = _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh, dry_run=True)
        assert gh.posted == []
        assert result.payload["comments"][0]["line"] == 12

    def test_empty_body_argument_still_yields_non_empty_body(self):
        gh = FakeGh()
        _run(_report(), gh, body="")
        assert gh.posted[0]["body"].strip()


# ---------------------------------------------------------------------------
# fallbacks
# ---------------------------------------------------------------------------
class TestThreadPagination:
    @pytest.mark.parametrize("has_more", [True, False])
    def test_page_cap_requires_complete_thread_list(
        self, has_more, tmp_path, monkeypatch, caplog
    ):
        class PagedGh(FakeGh):
            def __init__(self):
                super().__init__()
                self.cursors = []

            def request(self, method, path, payload=None):
                result = super().request(method, path, payload)
                if path == "graphql":
                    self.cursors.append(payload["variables"]["cursor"])
                    page = len(self.cursors)
                    conn = result["data"]["repository"]["pullRequest"]["reviewThreads"]
                    conn["pageInfo"] = {
                        "hasNextPage": page < 2 or has_more,
                        "endCursor": f"page-{page}",
                    }
                return result

        gh = PagedGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        monkeypatch.setattr(ppr, "_MAX_THREAD_PAGES", 2)
        report = _valid_report()
        report["metadata"].update(commit=HEAD, base_commit=MERGE_BASE)
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report))
        assert ppr.main(["o/r", "7", str(path)]) == (1 if has_more else 0)
        assert gh.cursors == [None, "page-1"]
        if has_more:
            assert gh.posted == []
            assert "pagination" in caplog.text
        else:
            assert gh.posted[0]["event"] == "APPROVE"


class TestFallbacks:
    def test_422_moves_inline_comments_into_body(self):
        gh = FakeGh(post_errors=[ppr.GhApiError(422, "Line could not be resolved")])
        result = _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh)
        first, second = gh.posted
        assert len(first["comments"]) == 1
        assert second["comments"] == []
        assert "SEC-001" in second["body"]
        assert result.inline == [] and result.in_body == ["SEC-001"]
        assert result.url.endswith("pullrequestreview-1")

    def test_rejected_approve_retries_as_comment(self):
        gh = FakeGh(
            post_errors=[
                ppr.GhApiError(422, "GitHub Actions is not permitted to approve")
            ]
        )
        result = _run(_report(), gh)
        assert [p["event"] for p in gh.posted] == ["APPROVE", "COMMENT"]
        assert result.event == "COMMENT"

    def test_other_errors_propagate(self):
        gh = FakeGh(post_errors=[ppr.GhApiError(500, "boom")])
        with pytest.raises(ppr.GhApiError):
            _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh)

    @pytest.mark.parametrize(
        ("report", "status"),
        [
            (_report(), 403),  # APPROVE rejected, then COMMENT rejected
            (_report(), 422),
            (_report(_finding("SEC-001", 4, "src/a.py:12")), 422),
        ],
    )
    def test_post_attempts_are_bounded(self, report, status):
        errors = [ppr.GhApiError(status, "nope") for _ in range(10)]
        gh = FakeGh(post_errors=errors)
        with pytest.raises(ppr.GhApiError):
            _run(report, gh)
        assert 1 <= len(gh.posted) <= 3

    def test_persistent_422_gives_up(self):
        errors = [ppr.GhApiError(422, "nope") for _ in range(5)]
        gh = FakeGh(post_errors=errors)
        with pytest.raises(ppr.GhApiError):
            _run(_report(_finding("SEC-001", 4, "src/a.py:12")), gh)
        assert len(gh.posted) == 2


# ---------------------------------------------------------------------------
# gh CLI adapter (subprocess faked)
# ---------------------------------------------------------------------------
class TestGhCli:
    def _cp(
        self, code: int, out: str = "", err: str = ""
    ) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], code, stdout=out, stderr=err)

    def test_success_parses_json_and_sends_payload_on_stdin(self):
        seen: list[tuple[list[str], str | None]] = []

        def runner(cmd, **kw):
            seen.append((cmd, kw.get("input")))
            return self._cp(0, '{"ok": 1}')

        client = ppr.GhCli(runner=runner, which=lambda _name: None)
        assert client.request("POST", "repos/o/r/pulls/7/reviews", {"a": 1}) == {
            "ok": 1
        }
        cmd, stdin = seen[0]
        assert cmd[:2] == ["gh", "api"] and "--input" in cmd
        assert json.loads(stdin) == {"a": 1}

    def test_http_status_is_parsed_from_stderr(self):
        client = ppr.GhCli(
            runner=lambda cmd, **kw: self._cp(
                1, '{"message":"Unprocessable"}', "gh: Unprocessable Entity (HTTP 422)"
            ),
            which=lambda _name: None,
        )
        with pytest.raises(ppr.GhApiError) as exc:
            client.request("POST", "x")
        assert exc.value.status == 422
        assert "Unprocessable" in str(exc.value)

    def test_403_retries_through_ghsudo_when_available(self):
        cmds: list[list[str]] = []

        def runner(cmd, **kw):
            cmds.append(cmd)
            if cmd[0] == "gh":
                return self._cp(1, "", "HTTP 403: Resource not accessible (HTTP 403)")
            return self._cp(0, "[]")

        client = ppr.GhCli(runner=runner, which=lambda name: "/usr/bin/ghsudo")
        assert client.request("GET", "x") == []
        assert cmds[1][:2] == ["ghsudo", "gh"]

    @pytest.mark.parametrize(
        ("method", "payload"),
        [
            ("POST", {"event": "APPROVE"}),
            ("PATCH", {"body": "x"}),
            ("POST", {"query": "mutation { resolveReviewThread }"}),
        ],
    )
    def test_writes_never_escalate_to_ghsudo(self, method, payload):
        cmds: list[list[str]] = []

        def runner(cmd, **kw):
            cmds.append(cmd)
            if cmd[0] == "gh":
                return self._cp(1, "", "HTTP 403: Forbidden")
            return self._cp(0, '{"html_url": "u"}')

        client = ppr.GhCli(runner=runner, which=lambda name: "/usr/bin/ghsudo")
        path = "graphql" if "query" in payload else "repos/o/r/pulls/7/reviews"
        with pytest.raises(ppr.GhApiError) as exc:
            client.request(method, path, payload)
        assert exc.value.status == 403
        assert [c[0] for c in cmds] == ["gh"]

    def test_graphql_read_query_may_escalate(self):
        cmds: list[list[str]] = []

        def runner(cmd, **kw):
            cmds.append(cmd)
            if cmd[0] == "gh":
                return self._cp(1, "", "HTTP 404: Not Found")
            return self._cp(0, '{"data": {}}')

        client = ppr.GhCli(runner=runner, which=lambda name: "/usr/bin/ghsudo")
        client.request("POST", "graphql", {"query": "\nquery($o: String!) { x }"})
        assert cmds[1][:2] == ["ghsudo", "gh"]

    def test_missing_gh_binary_raises_api_error(self):
        def runner(cmd, **kw):
            raise FileNotFoundError(cmd[0])

        client = ppr.GhCli(runner=runner, which=lambda name: None)
        with pytest.raises(ppr.GhApiError, match="not found"):
            client.request("GET", "x")

    def test_graphql_errors_raise(self):
        client = ppr.GhCli(
            runner=lambda cmd, **kw: self._cp(0, '{"errors":[{"message":"bad"}]}'),
            which=lambda _name: None,
        )
        with pytest.raises(ppr.GhApiError, match="bad"):
            ppr.graphql(client, "query{}", {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCli:
    def test_dry_run_prints_payload(self, tmp_path, capsys, monkeypatch):
        report = tmp_path / "report.json"
        finding = _finding("CODE-001", 4, "src/a.py:12")
        report.write_text(json.dumps(_valid_report(finding)))
        comments = tmp_path / "comments.json"
        comments.write_text(json.dumps({"CODE-001": "Look here."}))
        gh = FakeGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        code = ppr.main(
            [
                "o/r",
                "7",
                str(report),
                "--comments",
                str(comments),
                "--body",
                "One line.",
                "--dry-run",
            ]
        )
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["payload"]["comments"][0]["body"].endswith("Look here.")
        assert gh.posted == []

    @pytest.mark.parametrize(
        "argv",
        [["bad repo", "7", "r.json"], ["o/r", "0", "r.json"], ["o/r", "x", "r.json"]],
    )
    def test_invalid_arguments(self, argv, tmp_path):
        with pytest.raises(SystemExit) as exc:
            ppr.main(argv)
        assert exc.value.code == 2

    def test_comments_file_must_map_ids_to_text(self, tmp_path, capsys):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_report()))
        comments = tmp_path / "c.json"
        comments.write_text(json.dumps({"SEC-001": 5}))
        assert ppr.main(["o/r", "7", str(report), "--comments", str(comments)]) == 2

    def test_api_failure_exits_1(self, tmp_path, monkeypatch):
        report = tmp_path / "report.json"
        report.write_text(VALID_REPORT.read_text())
        gh = FakeGh(post_errors=[ppr.GhApiError(500, "boom")])
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        assert ppr.main(["o/r", "7", str(report)]) == 1


# ---------------------------------------------------------------------------
# approval safety
# ---------------------------------------------------------------------------
class TestApprovalSafety:
    @pytest.mark.parametrize("explicit_commit", [None, HEAD, "b" * 40])
    def test_stale_report_exits_2_without_posting(
        self, explicit_commit, tmp_path, monkeypatch, caplog
    ):
        report = _valid_report()
        report["metadata"]["commit"] = "b" * 40
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report))
        gh = FakeGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        argv = ["o/r", "7", str(path)]
        if explicit_commit:
            argv += ["--commit", explicit_commit]
        assert ppr.main(argv) == 2
        assert gh.posted == []
        assert (
            f"report is for {'b' * 40}, PR head is {HEAD}; re-run the review"
            in caplog.text
        )

    def test_explicit_commit_must_match_report(self):
        gh = FakeGh()
        with pytest.raises(ppr.ReportError, match="--commit.*metadata.commit"):
            _run(_report(), gh, commit="b" * 40)
        assert gh.posted == []

    @pytest.mark.parametrize("explicit_commit", [None, HEAD])
    def test_missing_reviewed_sha_downgrades_to_comment(self, explicit_commit, caplog):
        report = _report()
        del report["metadata"]["commit"]
        result = _run(report, FakeGh(), commit=explicit_commit)
        assert result.event == "COMMENT"
        assert "metadata.commit" in caplog.text and "COMMENT" in caplog.text

    def test_explicit_commit_without_metadata_must_match_diff_head(self):
        report = _report()
        del report["metadata"]
        gh = FakeGh()
        with pytest.raises(ppr.ReportError, match="PR head"):
            _run(report, gh, commit="b" * 40)
        assert gh.posted == []

    def test_head_change_during_diff_fetch_refuses_posting(self):
        class MovingHeadGh(FakeGh):
            def request(self, method, path, payload=None):
                result = super().request(method, path, payload)
                if path == "repos/o/r/pulls/7" and len(self.calls) > 1:
                    result["head"]["sha"] = "b" * 40
                return result

        gh = MovingHeadGh()
        with pytest.raises(ppr.ReportError, match="re-run the review"):
            _run(_report(), gh)
        assert gh.posted == []

    def test_null_comment_on_blocking_finding_does_not_approve(self):
        report = _report(_finding("SEC-001", 5, "src/a.py:11", merge_class="blocking"))
        result = _run(report, FakeGh(), comments={"SEC-001": None})
        assert result.event == "COMMENT"

    def test_null_comment_on_medium_finding_does_not_approve(self):
        result = _run(
            _report(_finding("SEC-001", 3, "src/a.py:11")),
            FakeGh(),
            comments={"SEC-001": None},
        )
        assert result.event == "COMMENT"

    def test_min_severity_filter_does_not_approve_over_unposted_high(self):
        result = _run(
            _report(_finding("QA-001", 4, "src/a.py:11")), FakeGh(), min_severity=5
        )
        assert result.event == "COMMENT" and result.inline == []

    def test_disputed_only_still_approves(self):
        report = _report(_finding("SEC-001", 5, "src/a.py:11", merge_class="disputed"))
        assert _run(report, FakeGh()).event == "APPROVE"

    def test_low_below_threshold_still_approves(self):
        assert (
            _run(_report(_finding("SEC-001", 2, "src/a.py:11")), FakeGh()).event
            == "APPROVE"
        )


class TestDiffScopeBinding:
    """APPROVE is bound to the reviewed merge-base, not only the head SHA."""

    def test_matching_merge_base_approves_via_compare_api(self):
        gh = FakeGh()
        assert _run(_report(), gh).event == "APPROVE"
        assert ("GET", f"repos/o/r/compare/{BASE_TIP}...{HEAD}?per_page=1") in gh.calls

    @pytest.mark.parametrize("findings", [(), (_finding("SEC-001", 4, "src/a.py:11"),)])
    def test_retargeted_base_exits_without_posting(self, findings):
        # Reviewed A...H; PR retargeted to an older base O: O...H is unreviewed.
        gh = FakeGh(merge_bases={BASE_TIP: "e" * 40})
        with pytest.raises(ppr.ReportError, match="diff scope changed"):
            _run(_report(*findings), gh)
        assert gh.posted == []

    def test_retarget_during_reads_is_caught(self):
        class RetargetingGh(FakeGh):
            def request(self, method, path, payload=None):
                if "/files" in path:
                    self.base_tip = "f" * 40
                return super().request(method, path, payload)

        gh = RetargetingGh(merge_bases={BASE_TIP: MERGE_BASE, "f" * 40: "e" * 40})
        with pytest.raises(ppr.ReportError, match="diff scope changed"):
            _run(_report(), gh)
        assert gh.posted == []

    def test_missing_base_commit_downgrades_to_comment(self, caplog):
        report = _report()
        del report["metadata"]["base_commit"]
        gh = FakeGh()
        assert _run(report, gh).event == "COMMENT"
        assert "metadata.base_commit" in caplog.text
        assert gh.posted[0]["event"] == "COMMENT"

    @pytest.mark.parametrize(
        "merge_base", [ppr.GhApiError(500, "boom"), ppr.GhApiError(404, "gone"), None]
    )
    def test_unverifiable_merge_base_posts_comment_not_failure(
        self, merge_base, caplog
    ):
        gh = FakeGh(merge_bases={BASE_TIP: merge_base})
        result = _run(_report(_finding("SEC-001", 4, "src/a.py:11")), gh)
        assert result.event == "COMMENT" and gh.posted[0]["event"] == "COMMENT"
        assert "merge-base" in caplog.text
        clean = _run(_report(), FakeGh(merge_bases={BASE_TIP: merge_base}))
        assert clean.event == "COMMENT"

    def test_cli_scope_mismatch_exits_2(self, tmp_path, monkeypatch, caplog):
        report = _valid_report()
        report["metadata"].update(commit=HEAD, base_commit="e" * 40)
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report))
        gh = FakeGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        assert ppr.main(["o/r", "7", str(path)]) == 2
        assert gh.posted == [] and "re-run the review" in caplog.text

    def test_schema_accepts_base_commit_and_rejects_short_sha(self):
        report = _valid_report()
        report["metadata"].update(commit=HEAD, base_commit=MERGE_BASE)
        ppr.check_schema(report)
        report["metadata"]["base_commit"] = "abc123"
        with pytest.raises(ppr.ReportError, match="base_commit"):
            ppr.check_schema(report)


# ---------------------------------------------------------------------------
# report validation
# ---------------------------------------------------------------------------
class TestReportValidation:
    @pytest.mark.parametrize(
        "report",
        [
            {},
            ["oops"],
            {"findings": None},
            {"finding": [{"findings": [_finding("X", 5, "src/a.py:11")]}]},
            {"schema_version": "4.0.0", "summary_statistics": {}, "findings": None},
            {
                "schema_version": "4.0.0",
                "summary_statistics": {},
                "findings": [{"title": "S", "findings": None}],
            },
            {
                "schema_version": "4.0.0",
                "summary_statistics": {},
                "findings": ["oops"],
            },
            {
                "schema_version": "4.0.0",
                "summary_statistics": {},
                "findings": [{"title": "S", "findings": ["oops"]}],
            },
            {
                "schema_version": "4.0.0",
                "summary_statistics": {},
                "findings": [{"title": "S", "findings": [{"title": "no id"}]}],
            },
            # intermediate.json / merged-findings.json are not assembled reports
            {"metadata": {}, "raw_findings": [], "duplicate_groups": []},
            {"metadata": {}, "executive_summary": {}, "findings": []},
        ],
    )
    def test_non_report_input_is_rejected(self, report):
        with pytest.raises(ppr.ReportError):
            ppr.validate_report(report)

    @pytest.mark.parametrize(
        "content", ["{}", '["oops"]', '{"findings": null}', '[{"findings": null}]']
    )
    def test_cli_bad_report_exits_2_without_posting(
        self, content, tmp_path, monkeypatch
    ):
        report = tmp_path / "report.json"
        report.write_text(content)
        gh = FakeGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        assert ppr.main(["o/r", "7", str(report)]) == 2
        assert gh.calls == []

    @pytest.mark.parametrize(
        "content",
        [
            '{"schema_version": "4.0.0", "summary_statistics": {}, "findings": []}',
            json.dumps(_report()),  # shape-valid but lacks executive_summary etc.
        ],
    )
    def test_cli_schema_invalid_report_exits_2_without_posting(
        self, content, tmp_path, monkeypatch
    ):
        report = tmp_path / "report.json"
        report.write_text(content)
        gh = FakeGh()
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        assert ppr.main(["o/r", "7", str(report)]) == 2
        assert gh.calls == []

    def test_cli_accepts_schema_valid_report(self, tmp_path, monkeypatch):
        report = tmp_path / "report.json"
        report.write_text(VALID_REPORT.read_text())
        monkeypatch.setattr(ppr, "GhCli", FakeGh)
        assert ppr.main(["o/r", "7", str(report), "--dry-run"]) == 0

    def test_cli_subprocess_no_traceback(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text('{"findings": null}')
        script = Path(ppr.__file__)
        proc = subprocess.run(
            [sys.executable, str(script), "o/r", "7", str(report), "--dry-run"],
            capture_output=True,
            text=True,
            env={"PATH": "/nonexistent"},
        )
        assert proc.returncode == 2 and "Traceback" not in proc.stderr

    def test_missing_gh_binary_is_clean_api_error(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(VALID_REPORT.read_text())
        proc = subprocess.run(
            [sys.executable, str(Path(ppr.__file__)), "o/r", "7", str(report)],
            capture_output=True,
            text=True,
            env={"PATH": "/nonexistent"},
        )
        assert proc.returncode == 1 and "Traceback" not in proc.stderr
        assert "gh" in proc.stderr


# ---------------------------------------------------------------------------
# GitHub size limits and text safety
# ---------------------------------------------------------------------------
class TestLimitsAndSanitizing:
    @pytest.mark.parametrize(
        "opening", ["```bad`info", "   ```bad`info", "    ```", "``", "~~", "`~~"]
    )
    def test_invalid_fence_is_sanitized_as_prose(self, opening):
        out = ppr.sanitize(f"{opening}\n<!--\n@team\n")
        assert "<!--" not in out
        assert "@team" not in out

    @pytest.mark.parametrize(
        ("opening", "closing"),
        [
            ("```python", "```"),
            ("   ````python", "  ````` \t"),
            ("~~~bad`info", "~~~~"),
        ],
    )
    def test_valid_fences_are_kept_and_everything_is_sanitized(self, opening, closing):
        out = ppr.sanitize(f"{opening}\n<!-- @inside\n{closing}\n<!-- @outside")
        assert out.startswith(f"{opening}\n<\u200b!-- @\u200binside\n{closing}\n")
        assert out.endswith("<\u200b!-- @\u200boutside")

    @pytest.mark.parametrize(
        "false_close",
        ["```info", "``` <!-- @team", "~~~", "``", "    ```", "```\u00a0"],
    )
    def test_invalid_closing_fence_keeps_block_open(self, false_close):
        text = f"```python\n{false_close}\n<!-- @inside\n"
        out = ppr.sanitize(text)
        # still open, so sanitize closes it; nothing inside stays live
        assert out.endswith("\n```")
        assert "<!--" not in out and "@inside" not in out

    def test_invalid_info_string_cannot_hide_later_off_diff_finding(self):
        report = _report(
            _finding("QA-001", 4, "other.py:1", description="```bad`info\n<!--\n"),
            _finding("QA-002", 4, "other.py:2", title="Second visible finding"),
        )
        result = _run(report, FakeGh())
        body = result.payload["body"]
        assert "<!--" not in body
        assert "**Second visible finding**" in body
        assert result.in_body == ["QA-001", "QA-002"]

    def test_body_overflow_lists_omitted_ids_and_in_body_is_truthful(self):
        findings = [
            _finding(f"QA-{i:03d}", 4, f"other/f{i}.py:1", description="x" * 3000)
            for i in range(1, 41)
        ]
        result = _run(_report(*findings), FakeGh(), dry_run=True)
        body = result.payload["body"]
        assert len(body) <= ppr.GITHUB_TEXT_LIMIT
        assert result.omitted, "expected overflow"
        assert all(f"**{fid}**" in body for fid in result.in_body)
        assert set(result.in_body) | set(result.omitted) == {f["id"] for f in findings}
        assert f"{len(result.omitted)} more finding(s)" in body
        assert result.omitted[0] in body.rsplit("more finding(s)", 1)[1]
        assert result.summary()["omitted"] == result.omitted

    def test_huge_inline_comment_is_clipped_and_stays_inline(self):
        report = _report(_finding("QA-001", 4, "src/a.py:11", description="y" * 70000))
        gh = FakeGh()
        result = _run(report, gh)
        [comment] = gh.posted[0]["comments"]
        assert len(comment["body"]) <= ppr.GITHUB_TEXT_LIMIT
        assert result.inline == ["QA-001"] and len(gh.posted) == 1

    def test_clip_closes_an_open_code_fence(self):
        text = "intro\n```python\n" + "x = 1\n" * 1000 + "```\nafter"
        clipped = ppr._clip(text, 200)
        assert len(clipped) <= 200
        assert clipped.count("```") % 2 == 0

    def test_mentions_everywhere_are_neutralized_but_emails_are_not(self):
        text = "cc @security-team and `@span` and\n```\n@fenced\n```\nmail a@b.io"
        out = ppr.sanitize(text)
        assert "@security-team" not in out
        assert "`@\u200bspan`" in out and "\n@\u200bfenced\n" in out
        assert "a@b.io" in out

    def test_code_span_never_crosses_a_paragraph(self):
        assert "@team" not in ppr.sanitize("a ` b\n\n@team\n\n` c")

    def test_unclosed_fence_is_closed(self):
        out = ppr.sanitize("```\n@inside")
        assert out.count("```") == 2 and "@\u200binside" in out

    def test_backtick_prefixed_mention_outside_span_is_neutralized(self):
        assert "@team" not in ppr.sanitize("dangling `@team")

    def test_html_comment_opener_is_neutralized(self):
        out = ppr.sanitize("<!-- hide the rest\nvisible? `<!-- code -->`")
        assert "<!--" not in out

    def test_posted_text_is_sanitized(self):
        report = _report(
            _finding("SEC-001", 5, "src/a.py:11", description="<!-- x cc @team"),
            _finding("SEC-002", 5, "other.py:9", description="ping @team"),
        )
        gh = FakeGh()
        _run(report, gh, body="@boss look")
        posted = json.dumps(gh.posted[0])
        assert "@team" not in posted and "@boss" not in posted
        assert "<!--" not in posted


class TestHeadingSurvivesClipping:
    """A finding reported as posted must be identifiable in the posted text."""

    FENCE = "`" * 2100

    def test_long_fence_in_body_keeps_id_title_and_location(self):
        report = _report(
            _finding(
                "QA-001", 4, "other.py:3", title="Fence bomb", description=self.FENCE
            )
        )
        result = _run(report, FakeGh(), dry_run=True)
        body = result.payload["body"]
        assert result.in_body == ["QA-001"]
        assert "**QA-001**" in body and "Fence bomb" in body and "other.py:3" in body

    def test_long_fence_inline_keeps_id_and_title(self):
        report = _report(
            _finding("QA-001", 4, "src/a.py:11", title="Big", description="`" * 70000)
        )
        result = _run(report, FakeGh(), dry_run=True)
        [comment] = result.payload["comments"]
        assert len(comment["body"]) <= ppr.GITHUB_TEXT_LIMIT
        assert "**QA-001**" in comment["body"] and "Big" in comment["body"]

    def test_clip_reserve_comes_from_retained_prefix(self):
        text = "keep me\n" + "x" * 3000 + "\n" + self.FENCE
        clipped = ppr._clip(text, 2000)
        assert len(clipped) <= 2000
        assert clipped.startswith("keep me\n" + "x" * 1500)

    @pytest.mark.parametrize("limit", [0, 5, 20, 2000])
    def test_clip_never_exceeds_limit_on_fence_only_text(self, limit):
        clipped = ppr._clip(self.FENCE, limit)
        assert len(clipped) <= max(limit, len("\n\n…(truncated)"))

    @pytest.mark.parametrize(
        "extra",
        [
            {"description": FENCE},
            {"description": "~" * 5000 + "\n@team <!--"},
            {"description": "y" * 70000},
            {"title": "T" * 5000},
            {"title": "@team <!-- `x`", "description": "```\n" + "z" * 3000},
            {"recommendation": "`" * 3000},
        ],
    )
    def test_every_posted_id_appears_in_posted_text(self, extra):
        report = _report(
            _finding("QA-001", 4, "src/a.py:11", **extra),
            _finding("QA-002", 4, "other.py:1", **extra),
            _finding("QA-003", 4, "other.py:2", **extra),
        )
        result = _run(report, FakeGh(), dry_run=True)
        comments = {c["body"] for c in result.payload["comments"]}
        body = result.payload["body"]
        assert result.inline == ["QA-001"]
        for fid in result.inline:
            assert any(f"**{fid}**" in c for c in comments)
        assert result.in_body
        for fid in result.in_body:
            assert f"**{fid}**" in body
        assert len(body) <= ppr.GITHUB_TEXT_LIMIT
        assert all(len(c) <= ppr.GITHUB_TEXT_LIMIT for c in comments)


class TestSanitizeStructure:
    """Outside valid GFM fences everything is neutralized; clip first, sanitize last."""

    def test_location_newline_cannot_open_html_comment_block(self):
        report = _report(
            _finding("QA-001", 4, "other.py:1\n\n<!--"),
            _finding("QA-002", 4, "other.py:2", title="Second visible finding"),
        )
        body = _run(report, FakeGh(), dry_run=True).payload["body"]
        assert "<!--" not in body
        assert "`other.py:1 <\u200b!--`" in body
        assert "**Second visible finding**" in body

    def test_title_is_collapsed_to_one_line(self):
        report = _report(_finding("QA-001", 4, "other.py:1", title="A\n\n<!--\tB"))
        body = _run(report, FakeGh(), dry_run=True).payload["body"]
        assert "**A <\u200b!-- B**" in body

    def test_mismatched_backtick_runs_do_not_exempt_comment_opener(self):
        assert "<!--" not in ppr.sanitize("``\n<!--\n`")

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("`@victim " + "x" * 3000 + "`", "@victim"),
            ("x" * 40 + "``@team " + "y" * 50 + "``", "@team"),
        ],
        ids=["long-span", "double-backtick"],
    )
    def test_clipping_cannot_revive_a_mention(self, text, name):
        out = ppr._fit(text, 80)
        assert "…(truncated)" in out
        assert name not in out and name.replace("@", "@\u200b") in out

    def test_clipped_span_in_posted_body_cannot_revive_a_mention(self):
        report = _report(
            _finding(
                "QA-001", 4, "other.py:1", description="`@victim " + "x" * 3000 + "`"
            )
        )
        body = _run(report, FakeGh(), dry_run=True).payload["body"]
        assert "@victim" not in body and "@\u200bvictim" in body

    def test_inline_code_span_is_neutralized(self):
        assert ppr.sanitize("see `@x` and `<!-- y -->`") == (
            "see `@\u200bx` and `<\u200b!-- y -->`"
        )

    def test_fenced_block_is_neutralized_too(self):
        # Fence detection can be fooled (e.g. by an HTML <pre> block), so
        # nothing is exempt: the fence stays, its dangerous tokens do not.
        out = ppr.sanitize("```python\n@decorator\n<!-- x -->\n```\n")
        assert out.startswith("```python\n") and out.endswith("```\n")
        assert "@decorator" not in out and "<!--" not in out

    def test_html_pre_block_cannot_fool_fence_detection(self):
        out = ppr.sanitize("<pre>\n```\n</pre>\n<!--")
        assert "<!--" not in out

    @pytest.mark.parametrize(
        "text",
        [
            "@a `@b` <!-- c",
            "```\n@inside",
            "``\n<!--\n`",
            "~~~\n@x\n~~~\n@y <!--",
            "@\u200bz <\u200b!--",
        ],
    )
    def test_sanitize_is_idempotent(self, text):
        once = ppr.sanitize(text)
        assert ppr.sanitize(once) == once
        assert "\u200b\u200b" not in once

    def test_limit_holds_after_zero_width_insertion(self):
        text = "@a " * 40000
        report = _report(
            _finding("QA-001", 4, "src/a.py:11", description=text),
            _finding("QA-002", 4, "other.py:1"),
        )
        gh = FakeGh()
        _run(report, gh, body=text)
        [comment] = gh.posted[0]["comments"]
        assert len(comment["body"]) <= ppr.GITHUB_TEXT_LIMIT
        assert len(gh.posted[0]["body"]) <= ppr.GITHUB_TEXT_LIMIT
        assert "@a " not in json.dumps(gh.posted[0])

    def test_fit_respects_limit_on_sanitized_text(self):
        out = ppr._fit("@a" * 50000, ppr.GITHUB_TEXT_LIMIT)
        assert len(out) <= ppr.GITHUB_TEXT_LIMIT
        assert ppr.sanitize(out) == out
