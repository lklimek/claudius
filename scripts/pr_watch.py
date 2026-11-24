#!/usr/bin/env python3
"""Wait for PR state changes; optionally check whether a review bot is working.

    pr_watch.py watch [options] <pr> [<pr> ...]
    pr_watch.py gate  [options] <pr>

``watch`` takes a full reading of each PR every ``--interval`` seconds and
prints one line per PR whose reading changed: state, review decision, draft
flag, unresolved review threads, non-passing checks (``green`` only once a
relevant check passed and none is pending; else ``none`` or, with
``--ignore-pending``, ``pending ignored``), plus the optional adapters
below. A reading that could not
be fetched, or whose Hygiene block describes an older head, is skipped for that
pass, never reported as a change. ``--oneshot`` exits 0 after the first pass
that printed, or 2 once ``ONESHOT_FAILED_READS`` full readings in a row failed
for every PR; ``--quiet-init`` records the first reading without printing it.
Every ``--probe-interval`` seconds in between, conditional REST requests on the
PR's issue record, its last-read head's check runs and statuses, and (with a gate bot) the first page of
comments answer 304 at no rate-limit cost while nothing changed; any change
triggers a full reading at once. Changes the probes cannot see, such as a
resolved review thread, show at the next full reading.

``gate`` prints ``feed: ...`` and ``gate: <updated_at> <status line>`` and exits
3 for observed running work, 0 for known non-running work, 2 for unknown evidence
or a fetch/usage error. These are observations, never push or merge permissions.

Adapters, both off unless their input exists:

* Hygiene: a ``<!-- pr-hygiene:start -->`` ... ``<!-- pr-hygiene:end -->``
  block in the PR body (heading ``# PR Hygiene · `<sha>```` and ``- [ ]`` items).
* Gate bot (``--gate-bot`` / ``GATE_BOT``): the bot's status comment, found by
  ``--gate-marker`` (default ``<bot>-gate``) and edited in place, so the newest
  ``updated_at`` wins, never creation order. Logins and repo names ignore case.
* Review feed (``--gate-feed-url`` / ``GATE_FEED_URL``): optional Reviewsys v1
  snapshot. ``watch`` enriches emitted events only, sharing one fetch per batch;
  feed-only changes do not wake it. Evidence matches repo/PR/head and includes
  freshness/health; absence is unknown. See git-and-github/references/reviewsys.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from review_feed import (
    Observation,
    SnapshotClient,
    combined_state,
    comment_observation,
    feed_observation,
    parse_ts,
)

EXIT_IDLE, EXIT_FAIL, EXIT_REVIEWING = 0, 2, 3
ONESHOT_FAILED_READS = 5
DEFAULT_BUSY = "Review in progress"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

HYGIENE_RE = re.compile(r"pr-hygiene:start(.*?)pr-hygiene:end", re.S)
HYGIENE_SHA_RE = re.compile(r"^# PR Hygiene · `([0-9a-f]+)`")
# CI values that --ignore-pending reads as one: checks settling is not a change.
SETTLING_CI_RE = re.compile(r" \|\| ci: (?:none|pending ignored|green)(?= \|\| |$)")
THREADS_QUERY = (
    "query($o:String!,$r:String!,$n:Int!,$c:String){repository(owner:$o,name:$r){"
    "pullRequest(number:$n){body headRefOid isDraft state reviewDecision "
    "reviewThreads(first:100,after:$c){pageInfo{hasNextPage endCursor} "
    "nodes{isResolved path line comments(first:1){nodes{author{login}}}}}}}}"
)
MAX_THREAD_PAGES = 20

# (returncode, stdout, stderr)
Runner = Callable[[list], "tuple[int, str, str]"]
Fetcher = Callable[[str], Optional[str]]


def run_gh(args: list) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout, p.stderr


fetch_url = SnapshotClient()


def first_line(err: str) -> str:
    return (err.strip().splitlines() or ["no output"])[0][:200]


def seconds(s: str) -> float:
    try:
        v = float(s)
    except ValueError:
        v = -1.0
    if not v >= 0:
        raise argparse.ArgumentTypeError(f"not a number of seconds: {s!r}")
    return v


def positive_seconds(s: str) -> float:
    v = seconds(s)
    if v == 0:
        raise argparse.ArgumentTypeError("must be more than 0 seconds")
    return v


def parse_http(out: str) -> tuple[int, str, str]:
    """Split ``gh api -i`` output into (status code, ETag, body); code 0 if unparseable."""
    head, _, body = out.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    m = re.match(r"HTTP/\S+ (\d{3})", lines[0])
    etag = next(
        (
            ln.split(":", 1)[1].strip()
            for ln in lines[1:]
            if ln.lower().startswith("etag:")
        ),
        "",
    )
    return (int(m.group(1)) if m else 0), etag, body


def regex(s: str) -> str:
    try:
        re.compile(s)
    except re.error as e:
        raise argparse.ArgumentTypeError(f"bad regex {s!r}: {e}") from None
    return s


# --- pure parsers -------------------------------------------------------------


def parse_hygiene(body: str) -> tuple[Optional[str], Optional[str]]:
    """Return (summary, head sha it describes); (None, None) without a block."""
    m = HYGIENE_RE.search(body.replace("\r", ""))
    if not m:
        return None, None
    lines = [
        ln
        for ln in m.group(1).split("\n")
        if ln.startswith("# PR Hygiene") or re.match(r"^ *- \[", ln)
    ]
    sha = None
    if lines and (s := HYGIENE_SHA_RE.match(lines[0])):
        sha = s.group(1)
    text = ";".join(lines) + ";"
    text = re.sub(r" — `/skip-bots`[^;]*", "", text)
    text = re.sub(r"files with no dedicated owner \([^)]*\)", "owner-less files", text)
    return text[:420], sha


def summarize_pr(pr: dict) -> tuple[str, str]:
    """Return (head sha, 'state=... unresolved=[...]') from the GraphQL PR node."""
    unresolved = []
    for t in pr["reviewThreads"]["nodes"]:
        if t["isResolved"]:
            continue
        nodes = t["comments"]["nodes"]
        login = ((nodes[0].get("author") or {}).get("login") if nodes else None) or "-"
        path = (t.get("path") or "").rsplit("/", 1)[-1]
        unresolved.append(f"{login}@{path}:{t.get('line')}")
    text = (
        f"state={pr['state']} decision={pr.get('reviewDecision') or '-'} "
        f"draft={str(pr['isDraft']).lower()} unresolved=[{','.join(unresolved)}]"
    )
    return pr["headRefOid"], text


def summarize_checks(
    checks: list, want: Optional[str] = None, ignore_pending: bool = False
) -> str:
    """Non-passing relevant checks; 'green' only once one passed and none is pending."""
    out, seen, passed, ignored = [], set(), False, False
    for c in checks:
        name, bucket = c.get("name") or "", c.get("bucket") or ""
        if not name or (want and not re.search(want, name)):
            continue
        if bucket in ("pass", "skipping"):
            passed = passed or bucket == "pass"
            continue
        if ignore_pending and bucket == "pending":
            ignored = True
            continue
        key = f"{name}={bucket}"
        if key not in seen:
            seen.add(key)
            out.append(key)
    if out:
        return " ".join(out)
    return "pending ignored" if ignored else "green" if passed else "none"


def same_name(value, name: str) -> bool:
    """GitHub logins and owner/repo names are case-insensitive."""
    return isinstance(value, str) and value.casefold() == name.casefold()


def gate_comment(
    comments: list, bot: str, marker: Optional[str] = None
) -> Optional[tuple[str, str]]:
    """Return (updated_at, first non-blank line) of the bot's newest-edited gate comment.

    Without ``marker`` the default ``<bot>-gate`` matches in any case, like the login.
    """
    best = None
    for c in comments:
        body = c.get("body") or ""
        if marker is None:
            found = f"{bot}-gate".casefold() in body.casefold()
        else:
            found = marker in body
        if not same_name(c.get("login"), bot) or not found:
            continue
        text = re.sub(r"<!--.*?-->", "", body, flags=re.S).replace("\r", "")
        line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
        ts = c.get("updated_at") or ""
        if best is None or (parse_ts(ts) or EPOCH) > (parse_ts(best[0]) or EPOCH):
            best = (ts, line)
    return best


# --- GitHub-backed reader -----------------------------------------------------


class Watcher:
    def __init__(
        self, args: argparse.Namespace, run: Runner = run_gh, fetch: Fetcher = fetch_url
    ) -> None:
        self.a, self.run, self.fetch = args, run, fetch
        self.owner, self.name = args.repo.split("/", 1)
        self.warned: dict = {}
        self.failed: set = set()
        self.etags: dict = {}  # pr -> {endpoint: etag}; "" = endpoint failed
        self.heads: dict = {}
        self.gates: dict = {}

    def warn(self, n: int, msg: str) -> None:
        """Report a failed fetch on stderr, once per PR per outage and error."""
        self.failed.add(n)
        if self.warned.get(n) != msg:
            self.warned[n] = msg
            print(f"pr_watch: PR{n}: {msg}", file=sys.stderr, flush=True)

    def probe(self, n: int) -> bool:
        """Conditional GETs (304 is free); True when an endpoint seen before changed.

        ``issues/{n}``, not ``pulls/{n}``: the latter embeds the repository's
        ``pushed_at``, so a push to any branch would look like a PR change. The
        head comes from the last full reading. A failing endpoint is skipped until
        the PR's next good full reading, so a token without access costs one
        request per full reading, not one per probe.
        """
        base = f"repos/{self.a.repo}"
        eps = [f"{base}/issues/{n}"]
        if n in self.heads:
            eps += [f"{base}/commits/{self.heads[n]}/check-runs?per_page=100"]
            eps += [f"{base}/commits/{self.heads[n]}/status"]
        if self.a.gate_bot:
            eps += [f"{base}/issues/{n}/comments?per_page=100"]
        changed = False
        for ep in eps:
            changed = self._conditional(n, ep) or changed
        return changed

    def _conditional(self, n: int, ep: str) -> bool:
        """True when ``ep`` answers 200 with an ETag other than the one seen last."""
        seen = self.etags.setdefault(n, {})
        if seen.get(ep) == "":
            return False
        cmd = ["api", "-i", ep]
        if seen.get(ep):
            cmd[2:2] = ["-H", f"If-None-Match: {seen[ep]}"]
        code, etag, _ = parse_http(self.run(cmd)[1])
        if code == 304:
            return False
        if code != 200 or not etag:
            seen[ep] = ""
            return False
        changed = ep in seen and seen[ep] != etag
        seen[ep] = etag
        return changed

    def retry_probes(self, n: int) -> None:
        """Forget failed endpoints so the next probe tries them again."""
        seen = self.etags.get(n, {})
        for ep in [ep for ep, etag in seen.items() if etag == ""]:
            del seen[ep]

    def gate(
        self, n: int, feed: bool = True
    ) -> Optional[tuple[str, str, Optional[bool]]]:
        """Return source evidence and running/known non-running/unknown; no policy."""
        a = self.a
        feed_url = feed and getattr(a, "gate_feed_url", None)
        rc, out, err = self.run(
            [
                "api",
                f"repos/{a.repo}/issues/{n}/comments",
                "--paginate",
                "--jq",
                ".[] | {login: .user.login, updated_at, body}",
            ]
        )
        try:
            comments = [json.loads(ln) for ln in out.split("\n") if ln.strip()]
        except ValueError:
            rc, err = 1, "unparseable comments response"
        if rc != 0:
            self.warn(n, "comments: " + first_line(err))
            return None
        g = gate_comment(comments, a.gate_bot, a.gate_marker or None)
        self.gates[n] = g
        gate_line = f"{g[0]} {g[1]}" if g else "none"
        busy = getattr(a, "gate_busy", DEFAULT_BUSY)
        if not feed:
            return "off", gate_line, None
        pr = self.pull_request(n)
        if pr is None:
            return None
        head = pr["headRefOid"]
        observation = (
            self.feed_evidence(n, head, self.fetch(feed_url))
            if feed_url
            else Observation("unknown", "off")
        )
        state = combined_state(observation, comment_observation(g, head, busy))
        running = (
            True
            if state == "running"
            else False
            if state in {"queued", "complete", "failed"}
            else None
        )
        return observation.text() if feed_url else "off", gate_line, running

    def feed_evidence(self, n: int, head: str, raw: Optional[str]) -> Observation:
        return feed_observation(raw, self.a.repo, n, head, max_age=self.a.feed_max_age)

    def enrich(self, n: int, reading: str, raw: Optional[str]) -> str:
        head = self.heads.get(n, "")
        observed = self.feed_evidence(n, head, raw)
        comment = comment_observation(self.gates.get(n), head, DEFAULT_BUSY)
        detail = observed.text()
        if (
            observed.state in {"running", "queued"}
            and comment.state in {"running", "queued", "complete", "failed"}
            and observed.state != comment.state
        ):
            detail += f" conflict=comment-{comment.state} combined=unknown"
        return f"{reading} || review-feed: {detail} head={head or 'unknown'}"

    def pull_request(self, n: int) -> Optional[dict]:
        """GraphQL PR node with every review-thread page merged; None on failure."""
        pr, threads, cursor = None, [], None
        for _ in range(MAX_THREAD_PAGES):
            cmd = ["api", "graphql", "-f", f"query={THREADS_QUERY}"]
            cmd += ["-f", f"o={self.owner}", "-f", f"r={self.name}", "-F", f"n={n}"]
            if cursor:
                cmd += ["-f", f"c={cursor}"]
            rc, out, err = self.run(cmd + ["--jq", ".data.repository.pullRequest"])
            try:
                page = json.loads(out) if rc == 0 else None
            except ValueError:
                page = None
            if not isinstance(page, dict):
                self.warn(n, "pull request: " + first_line(err))
                return None
            pr = pr or page
            conn = page.get("reviewThreads") or {}
            threads += conn.get("nodes") or []
            info = conn.get("pageInfo") or {}
            cursor = info.get("endCursor")
            if not (info.get("hasNextPage") and cursor):
                pr["reviewThreads"] = {"nodes": threads}
                return pr
        self.warn(n, f"pull request: over {MAX_THREAD_PAGES * 100} review threads")
        return None

    def reading(self, n: int) -> Optional[str]:
        a = self.a
        pr = self.pull_request(n)
        if pr is None:
            return None
        head, state = summarize_pr(pr)
        self.heads[n] = head
        hygiene, hsha = parse_hygiene(pr.get("body") or "")
        # After a push the block lags behind the head; wait for it to catch up.
        if hsha and not head.startswith(hsha):
            return None
        # gh exits non-zero for failing or pending checks too: judge by the output.
        rc, out, err = self.run(
            ["pr", "checks", str(n), "--repo", a.repo, "--json", "name,bucket"]
        )
        try:
            checks = json.loads(out)
        except ValueError:
            if "no checks reported" not in err:
                self.warn(n, "checks: " + first_line(err))
                return None
            checks = []
        parts = [state, "ci: " + summarize_checks(checks, a.checks, a.ignore_pending)]
        if hygiene:
            if a.ignore_pending:
                hygiene = re.sub(
                    r"^# PR Hygiene · `[0-9a-f]+`;", "# PR Hygiene;", hygiene
                )
                hygiene = re.sub(
                    r" *- \[[ x]\] Build (running|green)[^;]*;", "", hygiene
                )
            parts.append("hygiene: " + hygiene)
        if a.gate_bot:
            g = self.gate(n, feed=False)
            if g is None:
                return None
            line = g[1].split(" ", 1)[1] if " " in g[1] else g[1]
            line = line.split(" (commit")[0].split(" · ")[0][:70]
            if a.ignore_pending and re.search(a.gate_pending, line):
                line = "review pending"
            parts.append("gate: " + line)
        return " || ".join(parts)


def watch(
    w: Watcher,
    prs: list,
    out=sys.stdout,
    sleep: Callable[[float], None] = time.sleep,
    max_passes: int = 0,
) -> int:
    """Poll until a reading changes (oneshot) or max_passes ticks; see module doc."""
    interval, step = w.a.interval, w.a.probe_interval
    if not 0 < step < interval:
        step = interval
    per_full = max(1, int(interval // step)) if step else 1
    prev: dict = {}
    since_full: dict = {}  # pr -> ticks since its last full reading
    fails = dict.fromkeys(prs, 0)
    passes = 0
    while True:
        changed = False
        feed_read, feed_raw = False, None
        for n in prs:
            due = since_full.get(n, per_full) >= per_full
            if step < interval:
                hit = w.probe(n)  # also refreshes the baseline before a due reading
                if not (due or hit):
                    since_full[n] += 1
                    continue
            since_full[n] = 1
            w.failed.discard(n)
            try:
                cur = w.reading(n)
            except Exception as e:  # malformed response: a failed reading
                w.warn(n, f"{type(e).__name__}: {e}")
                cur = None
            if n in w.failed:
                fails[n] += 1
            else:
                fails[n] = 0
                w.warned.pop(n, None)
                w.retry_probes(n)
            key = cur
            if cur and w.a.ignore_pending:
                key = SETTLING_CI_RE.sub(" || ci: settling", cur, 1)
            if w.a.gate_feed_url:
                key = (key, w.heads.get(n))
            if cur is None or key == prev.get(n):
                continue
            if not w.a.quiet_init or n in prev:
                event = cur
                if w.a.gate_feed_url:
                    if not feed_read:
                        feed_raw, feed_read = w.fetch(w.a.gate_feed_url), True
                    event = w.enrich(n, cur, feed_raw)
                print(f"PR{n} {event}", file=out, flush=True)
                changed = True
            prev[n] = key
        passes += 1
        if w.a.oneshot and min(fails.values()) >= ONESHOT_FAILED_READS:
            print(
                f"pr_watch: every fetch failed {ONESHOT_FAILED_READS} times in a row; giving up",
                file=sys.stderr,
                flush=True,
            )
            return EXIT_FAIL
        if (w.a.oneshot and changed) or (max_passes and passes >= max_passes):
            return 0
        sleep(step)


def parse_args(argv: list) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo",
        default=os.environ.get("REPO"),
        help="owner/name; default: the current checkout's repository",
    )
    common.add_argument(
        "--gate-bot",
        default=os.environ.get("GATE_BOT"),
        help="login of the bot whose gate comment to read; unset: no gate",
    )
    common.add_argument(
        "--gate-marker",
        default=os.environ.get("GATE_MARKER"),
        help="text identifying the gate comment; default: <bot>-gate",
    )
    common.add_argument(
        "--gate-feed-url",
        default=os.environ.get("GATE_FEED_URL"),
        help="optional Reviewsys snapshot URL; watch reads it only for emitted events",
    )
    common.add_argument(
        "--feed-max-age",
        type=positive_seconds,
        default=900,
        help="maximum snapshot/ingest age in seconds (default 900)",
    )
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", parents=[common], help="print PR state changes")
    w.add_argument("prs", nargs="+", type=int)
    w.add_argument(
        "--checks", type=regex, help="regex of check names to watch; default: all"
    )
    w.add_argument(
        "--ignore-pending",
        action="store_true",
        help="ignore running checks, pending reviews and green builds; "
        "head changes still emit when a review feed is configured",
    )
    w.add_argument(
        "--gate-pending",
        type=regex,
        default=r"Review (not started|in progress)",
        help="regex: gate line that --ignore-pending reads as pending",
    )
    w.add_argument(
        "--quiet-init",
        action="store_true",
        help="record the first reading without printing it",
    )
    w.add_argument(
        "--oneshot",
        action="store_true",
        help="exit after the first pass that printed a change",
    )
    w.add_argument(
        "--interval",
        type=positive_seconds,
        default=os.environ.get("PR_WATCH_INTERVAL", "120"),
        help="seconds between full readings (env PR_WATCH_INTERVAL; default 120)",
    )
    w.add_argument(
        "--probe-interval",
        type=seconds,
        default=os.environ.get("PR_WATCH_PROBE_INTERVAL", "30"),
        help="seconds between free conditional probes; 0 or >= --interval disables "
        "them (env PR_WATCH_PROBE_INTERVAL; default 30)",
    )
    g = sub.add_parser("gate", parents=[common], help="is the gate bot reviewing now")
    g.add_argument("pr", type=int)
    g.add_argument(
        "--gate-busy",
        type=regex,
        default=DEFAULT_BUSY,
        help="regex: gate line meaning a review is running",
    )
    return p.parse_args(argv)


def main(
    argv: Optional[list] = None, run: Runner = run_gh, fetch: Fetcher = fetch_url
) -> int:
    a = parse_args(sys.argv[1:] if argv is None else argv)
    if not a.repo:
        rc, out, _ = run(
            ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
        )
        a.repo = out.strip() if rc == 0 else ""
    if "/" not in a.repo:
        print(
            "pr_watch: set --repo owner/name or run inside a checkout", file=sys.stderr
        )
        return EXIT_FAIL
    w = Watcher(a, run, fetch)
    if a.cmd == "watch":
        return watch(w, a.prs)
    if not a.gate_bot:
        print("pr_watch: gate needs --gate-bot or GATE_BOT", file=sys.stderr)
        return EXIT_FAIL
    try:
        g = w.gate(a.pr)
    except Exception as e:  # malformed response: never an implicit "not reviewing"
        print(f"pr_watch: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_FAIL
    if g is None:
        return EXIT_FAIL
    print(f"feed: {g[0]}\ngate: {g[1]}")
    if g[2] is None:
        print("state: unknown")
        return EXIT_FAIL
    return EXIT_REVIEWING if g[2] else EXIT_IDLE


if __name__ == "__main__":
    sys.exit(main())
