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
        "findings": [{"title": "S", "category": "security", "findings": list(findings)}]
    }


class FakeGh:
    """Records requests and replays canned responses per (method, path prefix)."""

    def __init__(
        self,
        *,
        files: list[dict[str, Any]] | None = None,
        threads: list[dict[str, Any]] | None = None,
        post_errors: list[ppr.GhApiError] | None = None,
    ) -> None:
        self.files = (
            files if files is not None else [{"filename": "src/a.py", "patch": PATCH_A}]
        )
        self.threads = threads or []
        self.post_errors = list(post_errors or [])
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
        if path.startswith("repos/o/r/pulls/7"):
            return {"head": {"sha": HEAD}}
        raise AssertionError(f"unexpected request {method} {path}")


def _thread(path: str, line: int | None, body: str, resolved: bool = False, **kw: Any):
    node = {
        "isResolved": resolved,
        "path": path,
        "line": line,
        "startLine": kw.get("start"),
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

    def test_null_comment_entry_skips_finding(self):
        report = _report(_finding("SEC-001", 4, "src/a.py:12"))
        gh = FakeGh()
        result = _run(report, gh, comments={"SEC-001": None})
        assert gh.posted[0]["comments"] == []
        assert result.skipped == ["SEC-001"]

    def test_findings_covered_by_open_threads_are_skipped(self):
        report = _report(
            _finding("SEC-001", 4, "src/a.py:11-12"),  # overlaps open thread line
            _finding("SEC-002", 4, "src/a.py:50", title="Unchecked parser error"),
            _finding("SEC-003", 4, "src/a.py:13"),  # only a resolved thread here
        )
        threads = [
            _thread("src/a.py", 12, "old wording"),
            _thread("src/a.py", None, "**unchecked parser error** again", original=3),
            _thread("src/a.py", 13, "fixed", resolved=True),
        ]
        gh = FakeGh(threads=threads)
        result = _run(report, gh)
        assert result.covered == ["SEC-001", "SEC-002"]
        assert [c["line"] for c in gh.posted[0]["comments"]] == [13]
        assert gh.posted[0]["event"] == "COMMENT"

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

    def test_explicit_commit_skips_pr_lookup(self):
        gh = FakeGh()
        _run(_report(), gh, commit="b" * 40)
        assert gh.posted[0]["commit_id"] == "b" * 40
        assert ("GET", "repos/o/r/pulls/7") not in gh.calls

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
        report.write_text(json.dumps(_report(_finding("SEC-001", 4, "src/a.py:12"))))
        comments = tmp_path / "comments.json"
        comments.write_text(json.dumps({"SEC-001": "Look here."}))
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
        report.write_text(json.dumps(_report()))
        gh = FakeGh(post_errors=[ppr.GhApiError(500, "boom")])
        monkeypatch.setattr(ppr, "GhCli", lambda: gh)
        assert ppr.main(["o/r", "7", str(report)]) == 1
