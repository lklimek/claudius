"""Tests for scripts/pr_watch.py on recorded gh / GraphQL / feed responses.

Fixtures in tests/fixtures/pr-watch/ are trimmed real responses (dashpay PR,
thepastaclaw gate comment and review-system feed). No test touches the network:
gh and the feed fetch are injected.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIX = REPO_ROOT / "tests" / "fixtures" / "pr-watch"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import pr_watch as pw  # noqa: E402

BODY = (FIX / "body-hygiene.md").read_text(encoding="utf-8")
PR = json.loads((FIX / "graphql-1167.json").read_text(encoding="utf-8"))
FEED = (FIX / "feed.json").read_text(encoding="utf-8")
COMMENTS = (FIX / "comments.jsonl").read_text(encoding="utf-8")
COMMENT_ROWS = [json.loads(ln) for ln in COMMENTS.splitlines()]
REPO = "dashpay/dash-evo-tool"


@pytest.fixture(autouse=True)
def _no_env_defaults(monkeypatch):
    for var in (
        "REPO",
        "GATE_BOT",
        "GATE_MARKER",
        "GATE_FEED_URL",
        "PR_WATCH_INTERVAL",
        "PR_WATCH_PROBE_INTERVAL",
    ):
        monkeypatch.delenv(var, raising=False)


def no_network(url):
    raise AssertionError(f"unexpected fetch of {url}")


class FakeGh:
    """Answers gh calls by subcommand; a value is (rc, stdout, stderr) or a list of them."""

    def __init__(self, **resp):
        self.resp = resp
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["api", "-i"]:
            key = "probe"
        elif args[0] == "api":
            key = "graphql" if args[1] == "graphql" else "comments"
        elif args[0] == "repo":
            key = "repo"
        else:
            key = args[1]  # view / checks
        r = self.resp[key]
        return r.pop(0) if isinstance(r, list) else r


def gh(body=BODY, pr=PR, checks=(0, "[]", ""), comments=(0, COMMENTS, "")):
    return FakeGh(
        graphql=(0, json.dumps(dict(pr, body=body)), ""),
        checks=checks,
        comments=comments,
    )


def args(cmd="watch", *extra):
    return pw.parse_args([cmd, "--repo", REPO, *extra, "1167"])


# --- pure parsers -------------------------------------------------------------


def test_hygiene_block_parsed_and_noise_trimmed():
    text, sha = pw.parse_hygiene(BODY)
    assert sha == "beee9f6"
    assert text.startswith("# PR Hygiene · `beee9f6`;- [x] Bots")
    assert "/skip-bots" not in text
    assert "owner-less files — lklimek" in text and "send_screen" not in text
    assert "When every merge" not in text


def test_hygiene_absent_is_skipped():
    assert pw.parse_hygiene("plain body") == (None, None)


def test_hygiene_crlf_body():
    text, sha = pw.parse_hygiene(BODY.replace("\n", "\r\n"))
    assert sha == "beee9f6" and "\r" not in text


def test_summarize_pr_lists_unresolved_only():
    pr = json.loads(json.dumps(PR))
    pr["reviewThreads"]["nodes"][0].update(isResolved=False, line=42)
    head, text = pw.summarize_pr(pr)
    assert head.startswith("beee9f6")
    assert text == (
        "state=OPEN decision=- draft=false unresolved=[thepastaclaw@payments.rs:42]"
    )


def test_summarize_pr_tolerates_deleted_author():
    pr = json.loads(json.dumps(PR))
    pr["reviewThreads"]["nodes"][0].update(isResolved=False)
    pr["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["author"] = None
    assert "unresolved=[-@payments.rs:None]" in pw.summarize_pr(pr)[1]


@pytest.mark.parametrize(
    ("ignore_pending", "want", "expected"),
    [
        (False, None, "lint=fail build=pending"),
        (True, None, "lint=fail"),
        (False, "^build$", "build=pending"),
        (True, "^build$", "green"),
    ],
)
def test_summarize_checks(ignore_pending, want, expected):
    checks = [
        {"name": "test", "bucket": "pass"},
        {"name": "lint", "bucket": "fail"},
        {"name": "lint", "bucket": "fail"},
        {"name": "build", "bucket": "pending"},
        {"name": "docs", "bucket": "skipping"},
    ]
    assert pw.summarize_checks(checks, want, ignore_pending) == expected


def test_feed_status_active_queued_idle():
    feed = json.loads(FEED)
    line, active = pw.feed_status(feed, "dashpay/tenderdash", 1586)
    assert active and "ACTIVE sha=f8cecf6fe" in line and "phase=phase1" in line
    line, active = pw.feed_status(feed, "dashpay/dash", 8062)
    assert not active and "queued" in line and "debounce" in line
    line, active = pw.feed_status(feed, REPO, 1167)
    assert line == "as_of=2026-11-06T15:57:01Z idle" and not active


def test_gate_comment_newest_edit_first_line_no_cr():
    # Multi-line CRLF body with emoji: first non-blank line, no \r; other bots'
    # comments and a human quoting the marker are ignored; newest updated_at wins
    # over an older gate comment regardless of order.
    ts, line = pw.gate_comment(COMMENT_ROWS, "thepastaclaw", "thepastaclaw-gate")
    assert ts == "2026-11-05T15:05:50Z"
    assert line.startswith("✅ Final review complete") and "\r" not in line
    assert "second line" not in line


def test_gate_comment_none():
    assert pw.gate_comment(COMMENT_ROWS, "other-bot", "other-bot-gate") is None


@pytest.mark.parametrize(
    ("active", "as_of", "gate", "expected"),
    [
        # Emoji prefix before the busy text still matches.
        (False, None, ("2026-11-06T10:00:00Z", "🔍 Review in progress"), True),
        # Stale feed ACTIVE vs newer gate "complete": the gate wins.
        (
            True,
            "2026-11-06T09:00:00Z",
            ("2026-11-06T10:00:00Z", "✅ Final review complete"),
            False,
        ),
        # Feed newer than the gate edit: ACTIVE wins.
        (
            True,
            "2026-11-06T11:00:00Z",
            ("2026-11-06T10:00:00Z", "✅ Final review complete"),
            True,
        ),
        (True, "2026-11-06T11:00:00Z", None, True),
        (False, None, ("2026-11-06T10:00:00Z", "⏳ Review not started"), False),
    ],
)
def test_is_reviewing(active, as_of, gate, expected):
    assert pw.is_reviewing(active, as_of, gate, "Review in progress") is expected


# --- reading / gate over fake gh ------------------------------------------------


def test_reading_without_adapters():
    a = args("watch")
    expected = "state=OPEN decision=- draft=false unresolved=[] || ci: green"
    assert pw.Watcher(a, gh(body="no block"), no_network).reading(1167) == expected
    # An empty description is a PR without a block, not a failed reading.
    assert pw.Watcher(a, gh(body=""), no_network).reading(1167) == expected


def test_reading_with_hygiene_and_gate_ignore_pending():
    a = args("watch", "--gate-bot", "thepastaclaw", "--ignore-pending")
    r = pw.Watcher(a, gh(), no_network).reading(1167)
    assert "hygiene: # PR Hygiene;- [x] Bots" in r
    assert "Build green" not in r
    assert r.endswith("gate: ✅ Final review complete — no blockers")


def test_reading_gate_pending_collapsed():
    rows = [
        dict(
            COMMENT_ROWS[0],
            body="<!-- thepastaclaw-gate v1 -->\r\n🔍 Review in progress (commit beee9f6b)",
        )
    ]
    comments = (0, "".join(json.dumps(x) + "\n" for x in rows), "")
    a = args("watch", "--gate-bot", "thepastaclaw", "--ignore-pending")
    r = pw.Watcher(a, gh(comments=comments), no_network).reading(1167)
    assert r.endswith("gate: review pending")


def test_reading_skips_stale_hygiene_head():
    pr = dict(PR, headRefOid="aaaaaaa" + "0" * 33)
    assert pw.Watcher(args("watch"), gh(pr=pr), no_network).reading(1167) is None


@pytest.mark.parametrize(
    ("graphql", "checks", "err"),
    [
        (
            (1, "", "HTTP 502: Bad Gateway\nmore"),
            (0, "[]", ""),
            "pull request: HTTP 502: Bad Gateway",
        ),
        ((0, "null", ""), (0, "[]", ""), "pull request: no output"),
        ((0, "not json", ""), (0, "[]", ""), "pull request: no output"),
        ((0, json.dumps(PR), ""), (1, "", "HTTP 502"), "checks: HTTP 502"),
    ],
    ids=["graphql-fail", "pr-null", "graphql-garbage", "checks-fail"],
)
def test_failed_fetch_is_skipped_and_reported(graphql, checks, err, capsys):
    w = pw.Watcher(args("watch"), FakeGh(graphql=graphql, checks=checks), no_network)
    assert w.reading(1167) is None
    assert w.reading(1167) is None
    # Reported once per PR per distinct error, on stderr only.
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err.splitlines() == [f"pr_watch: PR1167: {err}"]


def test_failing_checks_nonzero_exit_still_read():
    checks = (8, json.dumps([{"name": "lint", "bucket": "fail"}]), "")
    r = pw.Watcher(args("watch"), gh(body="x", checks=checks), no_network).reading(1167)
    assert r.endswith("ci: lint=fail")


def test_no_checks_reported_is_green():
    checks = (1, "", "no checks reported on the 'feat' branch")
    r = pw.Watcher(args("watch"), gh(body="x", checks=checks), no_network).reading(1167)
    assert r.endswith("ci: green")


def test_gate_comments_failure_skips_reading():
    a = args("watch", "--gate-bot", "thepastaclaw")
    w = pw.Watcher(a, gh(comments=(1, "", "HTTP 502")), no_network)
    assert w.reading(1167) is None


# --- watch loop ---------------------------------------------------------------


def _watch(extra, readings, passes=3):
    a = args("watch", "--probe-interval", "0", *extra)
    w = pw.Watcher(a, FakeGh())
    seq = iter(readings)
    w.reading = lambda n: next(seq)
    out = io.StringIO()
    rc = pw.watch(w, [1167], out=out, sleep=lambda s: None, max_passes=passes)
    return rc, out.getvalue().splitlines()


def test_watch_prints_changes_only():
    rc, lines = _watch([], ["a", "a", "b"])
    assert rc == 0 and lines == ["PR1167 a", "PR1167 b"]


def test_watch_survives_malformed_response(capsys):
    a = args("watch", "--probe-interval", "0")
    w = pw.Watcher(a, FakeGh())
    seq = iter([KeyError("reviewThreads"), "a"])

    def reading(n):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r

    w.reading = reading
    out = io.StringIO()
    assert pw.watch(w, [1167], out=out, sleep=lambda s: None, max_passes=2) == 0
    assert out.getvalue() == "PR1167 a\n"
    assert "PR1167: KeyError" in capsys.readouterr().err


def test_watch_quiet_init_oneshot_exits_on_first_change():
    rc, lines = _watch(
        ["--quiet-init", "--oneshot"], ["a", None, "a", "b", "c"], passes=0
    )
    assert rc == 0 and lines == ["PR1167 b"]


# --- CLI ----------------------------------------------------------------------


def _fetch_feed_active_for_1167(url):
    feed = json.loads(FEED)
    feed["live"]["active"].append(
        {"repo": REPO, "number": 1167, "sha": "beee9f6b", "phase": "phase2"}
    )
    return json.dumps(feed)


def test_gate_cli_exit_codes(capsys):
    base = ["gate", "--repo", REPO, "--gate-bot", "thepastaclaw", "1167"]
    assert pw.main(base, gh(), lambda url: None) == pw.EXIT_IDLE
    assert capsys.readouterr().out.startswith(
        "feed: off\ngate: 2026-11-05T15:05:50Z ✅"
    )
    # Feed ACTIVE newer than the gate edit -> reviewing.
    feed_args = [
        *base[:-1],
        "--gate-feed-url",
        "https://example.invalid/s.json",
        "1167",
    ]
    assert pw.main(feed_args, gh(), _fetch_feed_active_for_1167) == pw.EXIT_REVIEWING
    assert "ACTIVE" in capsys.readouterr().out
    assert pw.main(base, gh(comments=(1, "", "x")), no_network) == pw.EXIT_FAIL
    assert "PR1167: comments: x" in capsys.readouterr().err
    # Unreachable or malformed feed: reported, the gate comment still decides.
    for raw in (
        None,
        "garbage",
        json.dumps({"data_as_of": 5, "live": {"active": [1]}}),
    ):
        assert pw.main(feed_args, gh(), lambda url, raw=raw: raw) == pw.EXIT_IDLE
        out = capsys.readouterr().out
        assert out.startswith(("feed: unavailable", "feed: as_of=5 idle")), out


def test_gate_cli_unexpected_error_is_fetch_failure(capsys):
    def boom(args):
        raise RuntimeError("boom")

    base = ["gate", "--repo", REPO, "--gate-bot", "thepastaclaw", "1167"]
    assert pw.main(base, boom) == pw.EXIT_FAIL
    assert "RuntimeError: boom" in capsys.readouterr().err


def test_fetch_url_maps_http_protocol_errors(monkeypatch):
    def bad(*a, **k):
        raise pw.http.client.IncompleteRead(b"")

    monkeypatch.setattr(pw.urllib.request, "urlopen", bad)
    assert pw.fetch_url("https://example.invalid/s.json") is None


def test_naive_timestamps_compare_as_utc():
    gate = ("2026-11-06T10:00:00", "✅ Final review complete")
    assert pw.is_reviewing(True, "2026-11-06T09:00:00Z", gate, "x") is False
    assert pw.parse_ts(5) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["watch", "--checks", "(", "1"],
        ["watch", "--gate-pending", "[", "1"],
        ["gate", "--gate-busy", "(", "1"],
        ["watch", "--gate-feed-url", "https://x", "1"],
    ],
    ids=["checks", "gate-pending", "gate-busy", "feed-is-gate-only"],
)
def test_bad_options_rejected_by_argparse(argv):
    with pytest.raises(SystemExit) as e:
        pw.parse_args(argv)
    assert e.value.code == 2


def test_gate_cli_requires_bot(capsys):
    assert pw.main(["gate", "--repo", REPO, "1"], gh()) == pw.EXIT_FAIL
    assert "--gate-bot" in capsys.readouterr().err


def test_repo_resolved_from_checkout_or_rejected():
    fake = FakeGh(repo=(1, "", "not a git repository"))
    assert pw.main(["gate", "--gate-bot", "b", "1"], fake) == pw.EXIT_FAIL


# --- review regressions ---------------------------------------------------------


def test_gate_comment_rows_survive_nel_in_body():
    # gh --jq emits one compact JSON object per line (Go json escapes U+2028/9 but
    # not U+0085); a raw NEL inside a body is valid JSON and must not split a row.
    rows = [dict(COMMENT_ROWS[0], body=COMMENT_ROWS[0]["body"] + "\x85tail")]
    rows.append(
        {
            "login": "someone",
            "updated_at": "2026-11-06T10:00:00Z",
            "body": "copy-pasted\x85text",
        }
    )
    comments = (0, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "")
    g = pw.Watcher(
        args("gate", "--gate-bot", "thepastaclaw"), gh(comments=comments), no_network
    ).gate(1167)
    assert g is not None and "Final review complete" in g[1]


def test_feed_repo_and_bot_login_match_case_insensitively():
    # GitHub owner/repo names and logins are case-insensitive; a differently
    # cased --repo / --gate-bot must not turn a running review into "idle".
    feed = json.loads(_fetch_feed_active_for_1167(None))
    assert pw.feed_status(feed, "DashPay/Dash-Evo-Tool", 1167)[1] is True
    assert pw.gate_comment(COMMENT_ROWS, "ThePastaClaw", "thepastaclaw-gate")


def test_watch_oneshot_gives_up_when_every_fetch_keeps_failing(capsys):
    w = pw.Watcher(args("watch", "--oneshot", "--probe-interval", "0"), FakeGh())

    def reading(n):
        w.warn(n, "pull request: HTTP 401")
        return None

    w.reading = reading
    rc = pw.watch(w, [1, 2], out=io.StringIO(), sleep=lambda s: None)
    err = capsys.readouterr().err
    assert rc == pw.EXIT_FAIL
    assert f"failed {pw.ONESHOT_FAILED_READS} times in a row" in err
    assert err.count("PR1: pull request: HTTP 401") == 1


def test_watch_oneshot_keeps_waiting_while_one_pr_fetches():
    w = pw.Watcher(args("watch", "--oneshot", "--probe-interval", "0"), FakeGh())

    def reading(n):
        if n == 1:
            w.warn(n, "pull request: HTTP 502")
            return None
        return "a"

    w.reading = reading
    passes = pw.ONESHOT_FAILED_READS + 2
    rc = pw.watch(w, [1, 2], out=io.StringIO(), sleep=lambda s: None, max_passes=passes)
    assert rc == 0


def test_watch_reports_a_repeated_outage_after_recovery(capsys):
    w = pw.Watcher(args("watch", "--probe-interval", "0"), FakeGh())
    seq = iter([None, "a", None, "a", None])

    def reading(n):
        r = next(seq)
        if r is None:
            w.warn(n, "pull request: HTTP 502")
        return r

    w.reading = reading
    pw.watch(w, [7], out=io.StringIO(), sleep=lambda s: None, max_passes=5)
    assert capsys.readouterr().err.count("PR7: pull request: HTTP 502") == 3


# --- conditional probes ---------------------------------------------------------


def http(code, etag="", body=""):
    reason = {200: "OK", 304: "Not Modified", 403: "Forbidden"}.get(code, "X")
    head = f"HTTP/2.0 {code} {reason}\r\nContent-Type: application/json\r\n"
    if etag:
        head += f'Etag: "{etag}"\r\n'
    return (0 if code == 200 else 1, head + "\r\n" + body, "")


class ProbeGh:
    """Serves ``gh api -i`` probes from {endpoint: [responses]}, recording headers."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, args):
        assert args[:2] == ["api", "-i"], args
        self.calls.append(args)
        r = self.routes[args[-1]]
        return r.pop(0) if isinstance(r, list) else r


PULL = "repos/dashpay/dash-evo-tool/pulls/1167"
RUNS = "repos/dashpay/dash-evo-tool/commits/abc/check-runs?per_page=100"
STATUS = "repos/dashpay/dash-evo-tool/commits/abc/status"
ISSUE = "repos/dashpay/dash-evo-tool/issues/1167/comments?per_page=100"
PULL_BODY = json.dumps({"head": {"sha": "abc"}})


def test_parse_http_status_etag_and_body():
    assert pw.parse_http(http(304, "e1")[1]) == (304, '"e1"', "")
    assert pw.parse_http(http(200, "e2", PULL_BODY)[1]) == (200, '"e2"', PULL_BODY)
    assert pw.parse_http("not http")[0] == 0


def test_probe_baseline_then_304_then_change():
    fake = ProbeGh(
        {
            PULL: [http(200, "p1", PULL_BODY), http(304), http(304)],
            RUNS: [http(200, "r1", "{}"), http(304), http(200, "r2", "{}")],
            STATUS: http(304),
        }
    )
    w = pw.Watcher(args("watch"), fake, no_network)
    assert w.probe(1167) is False  # first sight is the baseline, not a change
    assert w.probe(1167) is False
    assert w.probe(1167) is True
    assert ["-H", 'If-None-Match: "r1"'] == fake.calls[-2][2:4]


def test_probe_reads_comments_only_with_a_gate_bot():
    routes = {PULL: http(304), ISSUE: http(304)}
    w = pw.Watcher(args("watch", "--gate-bot", "thepastaclaw"), ProbeGh(routes))
    w.probe(1167)
    assert [c[-1] for c in w.run.calls] == [PULL, ISSUE]
    w = pw.Watcher(args("watch"), ProbeGh(routes))
    w.probe(1167)
    assert [c[-1] for c in w.run.calls] == [PULL]


def test_failed_probe_endpoint_skipped_until_retried():
    fake = ProbeGh({PULL: [http(403), http(200, "p1", PULL_BODY)], RUNS: http(304)})
    w = pw.Watcher(args("watch"), fake)
    assert w.probe(1167) is False and w.probe(1167) is False
    assert len(fake.calls) == 1  # the 403 endpoint is not hammered
    w.retry_probes(1167)
    fake.routes[STATUS] = http(304)
    assert w.probe(1167) is False and fake.calls[1][-1] == PULL


def _probe_watch(hits, ticks, *extra):
    w = pw.Watcher(args("watch", "--interval", "120", *extra), FakeGh())
    probes, reads = iter(hits), []
    w.probe = lambda n: next(probes)
    w.reading = lambda n: reads.append(len(reads)) or str(len(reads))
    pw.watch(w, [1167], out=io.StringIO(), sleep=lambda s: None, max_passes=ticks)
    return reads


def test_watch_reads_on_probe_hit_and_every_interval():
    # 30 s probes, 120 s full readings: tick 1 reads, a hit at tick 3 reads at
    # once and restarts the 4-tick countdown, so the next full read is tick 7.
    hits = [False, False, True, False, False, False, False]
    assert len(_probe_watch(hits, 7)) == 3


def test_probe_interval_zero_or_not_below_interval_disables_probes():
    for v in ("0", "120", "300"):
        w = pw.Watcher(args("watch", "--probe-interval", v), FakeGh())
        w.probe = lambda n: pytest.fail("probed")
        w.reading = lambda n: "a"
        pw.watch(w, [1167], out=io.StringIO(), sleep=lambda s: None, max_passes=2)


def test_intervals_from_env_and_validated(monkeypatch):
    monkeypatch.setenv("PR_WATCH_INTERVAL", "300")
    monkeypatch.setenv("PR_WATCH_PROBE_INTERVAL", "15")
    a = args("watch")
    assert (a.interval, a.probe_interval) == (300.0, 15.0)
    assert args("watch", "--interval", "60").interval == 60.0
    for bad in ("-1", "abc", "nan"):
        with pytest.raises(SystemExit):
            args("watch", "--interval", bad)


def test_default_gate_marker_matches_any_case_explicit_marker_exact():
    assert pw.gate_comment(COMMENT_ROWS, "ThePastaClaw")
    assert pw.gate_comment(COMMENT_ROWS, "thepastaclaw", "ThePastaClaw-gate") is None


def test_gate_cli_default_marker_with_differently_cased_bot(capsys):
    fake = gh()
    rc = pw.main(["gate", "--repo", REPO, "--gate-bot", "ThePastaClaw", "1167"], fake)
    assert "gate: none" not in capsys.readouterr().out and rc in (0, 3)


def _thread(login, line, resolved=False):
    return {
        "isResolved": resolved,
        "path": "src/a.rs",
        "line": line,
        "comments": {"nodes": [{"author": {"login": login}}]},
    }


def test_review_threads_followed_across_pages():
    page1 = dict(
        PR,
        body="",
        reviewThreads={
            "pageInfo": {"hasNextPage": True, "endCursor": "C1"},
            "nodes": [_thread("a", 1, resolved=True)] * 100,
        },
    )
    page2 = dict(
        PR,
        body="",
        reviewThreads={
            "pageInfo": {"hasNextPage": False, "endCursor": "C2"},
            "nodes": [_thread("late-bot", 7)],
        },
    )
    fake = FakeGh(
        graphql=[(0, json.dumps(page1), ""), (0, json.dumps(page2), "")],
        checks=(0, "[]", ""),
    )
    r = pw.Watcher(args("watch"), fake, no_network).reading(1167)
    assert "unresolved=[late-bot@a.rs:7]" in r
    gql = [c for c in fake.calls if c[1] == "graphql"]
    assert "c=C1" in gql[1] and not any(x.startswith("c=") for x in gql[0])


def test_review_thread_page_limit_is_a_failed_reading(capsys):
    page = dict(
        PR,
        reviewThreads={
            "pageInfo": {"hasNextPage": True, "endCursor": "X"},
            "nodes": [],
        },
    )
    fake = FakeGh(graphql=(0, json.dumps(page), ""))
    assert pw.Watcher(args("watch"), fake, no_network).reading(1167) is None
    assert "review threads" in capsys.readouterr().err


@pytest.mark.xfail(strict=True, reason="per_full = round(interval / step)")
def test_full_readings_at_most_interval_apart():
    for probe in ("50", "70", "80", "100"):
        a = args("watch", "--interval", "120", "--probe-interval", probe)
        w, now, reads = pw.Watcher(a, FakeGh()), [0.0], []
        w.probe = lambda n: False
        w.reading = lambda n: reads.append(now[0]) or "a"

        def sleep(s):
            now[0] += s

        pw.watch(w, [1167], out=io.StringIO(), sleep=sleep, max_passes=12)
        gaps = [b - a for a, b in zip(reads, reads[1:])]
        assert gaps and max(gaps) <= 120, (probe, gaps)


@pytest.mark.xfail(strict=True, reason="pulls ETag covers base.repo.pushed_at")
def test_probe_ignores_repo_wide_push_in_embedded_repo():
    def pull(pushed_at):
        repo = {"full_name": REPO, "pushed_at": pushed_at}
        return json.dumps(
            {"head": {"sha": "abc", "repo": repo}, "base": {"repo": repo}}
        )

    fake = ProbeGh(
        {
            PULL: [http(200, "p1", pull("t1")), http(200, "p2", pull("t2"))],
            RUNS: http(304),
            STATUS: http(304),
        }
    )
    w = pw.Watcher(args("watch"), fake, no_network)
    assert w.probe(1167) is False
    assert w.probe(1167) is False  # another branch was pushed; this PR is unchanged
