"""Read-only Reviewsys snapshot evidence; no publication or readiness decisions."""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def parse_ts(ts: object) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Observation:
    state: str
    detail: str
    as_of: Optional[str] = None

    def text(self) -> str:
        return f"{self.state} {self.detail}" + (
            f" as_of={self.as_of}" if self.as_of else ""
        )


def comment_observation(gate, head: str, busy: str) -> Observation:
    if not gate:
        return Observation("unknown", "no authored status comment")
    updated, line = gate
    commit = re.search(r"\bcommit\s+`?([0-9a-f]{7,40})\b", line)
    if not commit or not parse_ts(updated):
        return Observation("unknown", "comment lacks commit or timestamp")
    if not head.startswith(commit[1]):
        return Observation("obsolete-head", f"comment sha={commit[1]}", updated)
    state = "unknown"
    if re.search(busy, line):
        state = "running"
    elif re.search(r"Review not started|\bqueued\b", line, re.I):
        state = "queued"
    elif re.search(r"Final review complete|Earlier review stands", line, re.I):
        state = "complete"
    elif re.search(r"Could not complete|\bfailed\b", line, re.I):
        state = "failed"
    return Observation(state, "status comment", updated)


def combined_state(feed: Observation, comment: Observation) -> str:
    known = {"running", "queued", "complete", "failed"}
    states = {item.state for item in (feed, comment) if item.state in known}
    return states.pop() if len(states) == 1 else "unknown"


def feed_observation(
    raw: Optional[str],
    repo: str,
    number: int,
    head: str,
    *,
    now: Optional[datetime] = None,
    max_age: float = 900,
) -> Observation:
    now = now or datetime.now(timezone.utc)
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return Observation("unknown", "current head unavailable")
    try:
        data = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        data = None
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
    ):
        return Observation("unknown", "unavailable or unsupported snapshot")
    live, as_of = data.get("live"), data.get("data_as_of")

    def unknown(reason: str) -> Observation:
        return Observation("unknown", reason, as_of if isinstance(as_of, str) else None)

    def fresh(value: object) -> bool:
        ts = parse_ts(value)
        return ts is not None and -60 <= (now - ts).total_seconds() <= max_age

    if not fresh(as_of) or ("generated_at" in data and not fresh(data["generated_at"])):
        return unknown("stale or invalid snapshot time")
    if not isinstance(live, dict):
        return unknown("invalid live data")
    watchdog = live.get("watchdog")
    if (
        not fresh(live.get("ingest_last_at"))
        or live.get("ingest_error_streak") != 0
        or not isinstance(watchdog, dict)
        or watchdog.get("ingest_stale") is not False
    ):
        return unknown("ingest unavailable or stale")
    health = []
    degraded = live.get("degraded")
    if isinstance(degraded, dict) and degraded.get("active"):
        health.append(str(degraded.get("mode") or "degraded"))
    if watchdog.get("stuck"):
        health.append("stuck")
    suffix = " health=" + ",".join(health) if health else ""
    matches, obsolete = [], False
    for key, state in (("active", "running"), ("queued", "queued")):
        rows = live.get(key)
        if not isinstance(rows, list):
            return unknown("invalid queue data")
        for row in rows:
            if not isinstance(row, dict):
                return unknown("invalid queue entry")
            if key == "active" and row.get("queue") != "live":
                continue
            if (
                not isinstance(row.get("repo"), str)
                or type(row.get("number")) is not int
                or not isinstance(row.get("sha"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", row["sha"])
            ):
                return unknown("invalid entry identity")
            if row["repo"].casefold() != repo.casefold() or row["number"] != number:
                continue
            if row["sha"] != head:
                obsolete = True
                continue
            fields = (
                ("phase", "started_at")
                if key == "active"
                else ("eligible_at", "reason")
            )
            detail = " ".join(
                f"{field}={' '.join(str(row[field]).split())[:120]}"
                for field in fields
                if row.get(field) is not None
            )
            matches.append(Observation(state, detail + suffix, as_of))
    if len(matches) > 1:
        return unknown("conflicting live entries" + suffix)
    if matches:
        return matches[0]
    return Observation(
        "obsolete-head" if obsolete else "unknown",
        "no matching current-head entry" + suffix,
        as_of,
    )


class SnapshotClient:
    """Cache snapshots and conditional GETs; failed reads back off for one minute."""

    def __init__(self, opener=None, clock=time.monotonic):
        self.opener, self.clock = opener, clock
        self.cache: dict = {}

    def __call__(self, url: str) -> Optional[str]:
        cached = self.cache.get(url, {})
        if self.clock() < cached.get("until", 0):
            return cached.get("raw")
        headers = {}
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("modified"):
            headers["If-Modified-Since"] = cached["modified"]
        try:
            request = urllib.request.Request(url, headers=headers)
            with (self.opener or urllib.request.urlopen)(
                request, timeout=20
            ) as response:
                raw, response_headers = (
                    response.read().decode("utf-8"),
                    response.headers,
                )
        except urllib.error.HTTPError as error:
            if error.code != 304 or cached.get("raw") is None:
                self.cache[url] = {"until": self.clock() + 60}
                return None
            raw, response_headers = cached["raw"], error.headers or {}
        except (OSError, ValueError, http.client.HTTPException):
            self.cache[url] = {"until": self.clock() + 60}
            return None
        cache_control = response_headers.get("Cache-Control", "")
        age = re.search(r"(?:^|,)\s*max-age=(\d+)", cache_control)
        try:
            elapsed = max(0, int(response_headers.get("Age", "0")))
        except ValueError:
            elapsed = 0
        ttl = max(0, int(age[1]) - elapsed) if age else 60
        if "no-store" in cache_control:
            self.cache.pop(url, None)
            return raw
        if "no-cache" in cache_control:
            ttl = 0
        self.cache[url] = {
            "raw": raw,
            "until": self.clock() + ttl,
            "etag": response_headers.get("ETag", cached.get("etag")),
            "modified": response_headers.get("Last-Modified", cached.get("modified")),
        }
        return raw
