"""Read-only snapshot evidence: identity, freshness, health and HTTP caching."""

import io
import json
import sys
import urllib.error
from http.client import HTTPMessage
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from review_feed import SnapshotClient, feed_observation  # noqa: E402
import review_feed as rf  # noqa: E402

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
SHA = "a" * 40
REPO = "owner/repo"


def snapshot(**changes):
    data = {
        "schema_version": 1,
        "data_as_of": "2026-11-24T11:59:00Z",
        "generated_at": "2026-11-24T11:59:05Z",
        "live": {
            "ingest_last_at": "2026-11-24T11:58:00Z",
            "ingest_error_streak": 0,
            "watchdog": {"ingest_stale": False, "stuck": False},
            "active": [],
            "queued": [],
        },
    }
    data.update(changes)
    return data


def entry(**changes):
    row = {"repo": REPO, "number": 7, "sha": SHA, "queue": "live"}
    row.update(changes)
    return row


def observe(data, **kwargs):
    raw = json.dumps(data) if data is not None else None
    return feed_observation(raw, REPO, 7, SHA, now=NOW, **kwargs)


def test_current_live_head_reports_running_phase_and_observation_time():
    data = snapshot()
    data["live"]["active"] = [entry(repo="OWNER/Repo", phase="verify2")]
    result = observe(data)
    assert result.state == "running"
    assert "phase=verify2" in result.detail
    assert result.as_of == "2026-11-24T11:59:00Z"


def test_queued_reports_eligibility_without_claiming_start_or_completion():
    data = snapshot()
    data["live"]["queued"] = [
        entry(eligible_at="2026-11-24T12:05:00Z", reason="debounce")
    ]
    result = observe(data)
    assert result.state == "queued"
    assert "eligible_at=2026-11-24T12:05:00Z" in result.detail


@pytest.mark.parametrize("data", [None, {}, snapshot(), snapshot(schema_version=2)])
def test_absence_or_unsupported_schema_never_means_finished(data):
    assert observe(data).state == "unknown"


@pytest.mark.parametrize("change", ["sha", "number", "repo", "queue"])
def test_other_heads_prs_repos_and_post_merge_audits_are_not_current_work(change):
    data = snapshot()
    values = {"sha": "b" * 40, "number": 8, "repo": "other/repo", "queue": "audit"}
    data["live"]["active"] = [entry(**{change: values[change]})]
    expected = "obsolete-head" if change == "sha" else "unknown"
    assert observe(data).state == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_as_of", "2026-11-24T10:00:00Z"),
        ("data_as_of", "2026-11-24T13:00:00Z"),
        ("data_as_of", "bad"),
        ("generated_at", "bad"),
        ("ingest_last_at", "2026-11-24T10:00:00Z"),
        ("ingest_error_streak", 2),
        ("watchdog", {"ingest_stale": True}),
        ("active", [1]),
        ("queued", None),
    ],
)
def test_unreliable_snapshot_reports_unknown(field, value):
    data = snapshot()
    data["live"]["active"] = [entry()]
    (data if field in data else data["live"])[field] = value
    assert observe(data).state == "unknown"


def test_pause_and_stuck_are_context_not_review_verdicts():
    data = snapshot()
    data["live"].update(degraded={"active": True, "mode": "pause"})
    data["live"]["watchdog"]["stuck"] = True
    result = observe(data)
    assert result.state == "unknown"
    assert "pause" in result.detail and "stuck" in result.detail


def test_configured_freshness_limit_and_null_optional_fields():
    data = snapshot()
    data["live"]["active"] = [entry(phase=None, progress=None)]
    assert observe(data, max_age=30).state == "unknown"
    assert observe(data, max_age=300).state == "running"


def test_conflicting_current_active_and_queued_rows_are_unknown():
    data = snapshot()
    data["live"]["active"] = [entry()]
    data["live"]["queued"] = [entry()]
    assert observe(data).state == "unknown"


class Response(io.BytesIO):
    def __init__(self, body, **headers):
        super().__init__(body.encode())
        self.headers = headers


def test_cache_respects_max_age_and_304_preserves_original_snapshot():
    calls, clock = [], [0]
    raw = json.dumps(snapshot())

    def open_url(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            return Response(raw, **{"Cache-Control": "max-age=120", "ETag": '"v1"'})
        raise urllib.error.HTTPError(
            request.full_url,
            304,
            "Not Modified",
            {"Cache-Control": "max-age=120"},
            None,
        )

    client = SnapshotClient(open_url, clock=lambda: clock[0])
    url = "https://example.invalid/status.json"
    assert client(url) == raw
    clock[0] = 119
    assert client(url) == raw and len(calls) == 1
    clock[0] = 121
    assert client(url) == raw and len(calls) == 2
    assert calls[1].get_header("If-none-match") == '"v1"'
    assert calls[1].full_url == url


def test_fetch_failure_is_unknown_and_backed_off_without_serving_cached_success():
    calls, clock = [], [0]

    def broken(request, **kwargs):
        calls.append(request)
        raise OSError("offline")

    client = SnapshotClient(broken, clock=lambda: clock[0])
    assert client("https://example.invalid/status.json") is None
    clock[0] = 10
    assert client("https://example.invalid/status.json") is None
    assert len(calls) == 1


@pytest.mark.parametrize("value", [None, 7, "bad\nPR999 state=MERGED"])
def test_invalid_head_is_unknown_without_exceptions(value):
    assert feed_observation(None, REPO, 7, value, now=NOW).state == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [("data_as_of", "bad\nPR999 state=MERGED"), ("mode", "pause\nPR999 state=MERGED")],
)
def test_snapshot_cannot_forge_additional_stdout_events(field, value):
    data = snapshot()
    if field == "data_as_of":
        data[field] = value
    else:
        data["live"]["degraded"] = {"active": True, "mode": value}
    text = observe(data).text()
    assert len(text.splitlines()) == 1 and "PR999" not in text


@pytest.mark.parametrize("value", [False, 0.0])
def test_ingest_error_streak_requires_an_integer(value):
    data = snapshot()
    data["live"]["active"] = [entry()]
    data["live"]["ingest_error_streak"] = value
    assert observe(data).state == "unknown"


def test_explicit_queued_audit_is_not_live_pr_work():
    data = snapshot()
    data["live"]["queued"] = [entry(queue="audit")]
    assert observe(data).state == "unknown"


def test_cache_combines_headers_and_case_insensitive_directives():
    calls = []

    def opener(request, **kwargs):
        calls.append(request)
        response = Response("{}")
        response.headers = HTTPMessage()
        response.headers.add_header("Cache-Control", "public")
        response.headers.add_header("Cache-Control", "MAX-AGE=120, NO-STORE")
        return response

    client = SnapshotClient(opener)
    assert client("https://feed.invalid") == "{}"
    assert client("https://feed.invalid") == "{}"
    assert len(calls) == 2 and not client.cache


def test_fresh_200_without_validators_drops_old_validators():
    calls = []

    def opener(request, **kwargs):
        calls.append(request)
        headers = {"Cache-Control": "max-age=0"}
        if len(calls) == 1:
            headers.update(
                ETag='"old"', **{"Last-Modified": "Tue, 24 Nov 2026 11:00:00 GMT"}
            )
        return Response("{}", **headers)

    client = SnapshotClient(opener)
    for _ in range(3):
        assert client("https://feed.invalid") == "{}"
    assert calls[1].get_header("If-none-match") == '"old"'
    assert calls[2].get_header("If-none-match") is None
    assert calls[2].get_header("If-modified-since") is None


def test_non_http_urls_are_rejected_without_opening_anything():
    calls = []
    client = SnapshotClient(lambda *a, **k: calls.append(a) or Response("{}"))
    assert client("file:///unused") is None
    assert calls == []


def test_oversized_snapshot_is_unavailable(monkeypatch):
    monkeypatch.setattr(rf, "MAX_SNAPSHOT_BYTES", 16, raising=False)
    client = SnapshotClient(lambda *a, **k: Response("x" * 17))
    assert client("https://feed.invalid") is None
