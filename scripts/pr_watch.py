#!/usr/bin/env python3
"""Wait for PR state changes; optionally check whether a review bot is working.

    pr_watch.py watch [options] <pr> [<pr> ...]
    pr_watch.py gate  [options] <pr>

``watch`` polls every ``--interval`` seconds and prints one line per PR whose
reading changed: state, review decision, draft flag, unresolved review threads,
non-passing checks, plus the optional adapters below. A reading that could not
be fetched, or whose Hygiene block describes an older head, is skipped for that
pass, never reported as a change. ``--oneshot`` exits 0 after the first pass
that printed; ``--quiet-init`` records the first reading without printing it.

``gate`` prints ``feed: ...`` and ``gate: <updated_at> <status line>`` and exits
3 while the gate bot is reviewing the PR (do not push), 0 when it is not, 2 on a
fetch failure or bad usage.

Adapters, both off unless their input exists:

* Hygiene: a ``<!-- pr-hygiene:start -->`` ... ``<!-- pr-hygiene:end -->``
  block in the PR body (heading ``# PR Hygiene · `<sha>```` and ``- [ ]`` items).
* Gate bot (``--gate-bot`` / ``GATE_BOT``): the bot's status comment, found by
  ``--gate-marker`` (default ``<bot>-gate``) and edited in place, so the newest
  ``updated_at`` wins, never creation order. ``gate`` with ``--gate-feed-url``
  / ``GATE_FEED_URL`` also reads a JSON status feed shaped
  ``{"data_as_of", "live": {"active": [...], "queued": [...]}}`` with entries
  ``{"repo": "owner/name", "number", "sha", ...}``. Both lag; the newer wins.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

EXIT_IDLE, EXIT_FAIL, EXIT_REVIEWING = 0, 2, 3
DEFAULT_BUSY = "Review in progress"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

HYGIENE_RE = re.compile(r"pr-hygiene:start(.*?)pr-hygiene:end", re.S)
HYGIENE_SHA_RE = re.compile(r"^# PR Hygiene · `([0-9a-f]+)`")
THREADS_QUERY = (
    "query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){"
    "pullRequest(number:$n){body headRefOid isDraft state reviewDecision "
    "reviewThreads(first:100){nodes{isResolved path line "
    "comments(first:1){nodes{author{login}}}}}}}}"
)

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


def fetch_url(url: str) -> Optional[str]:
    sep = "&" if "?" in url else "?"
    try:
        with urllib.request.urlopen(f"{url}{sep}t={int(time.time())}", timeout=20) as r:
            return r.read().decode("utf-8")
    except (OSError, ValueError, http.client.HTTPException):
        return None


def parse_ts(ts: object) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def first_line(err: str) -> str:
    return (err.strip().splitlines() or ["no output"])[0][:200]


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
    out, seen = [], set()
    for c in checks:
        name, bucket = c.get("name") or "", c.get("bucket") or ""
        if not name or bucket in ("pass", "skipping"):
            continue
        if want and not re.search(want, name):
            continue
        if ignore_pending and bucket == "pending":
            continue
        key = f"{name}={bucket}"
        if key not in seen:
            seen.add(key)
            out.append(key)
    return " ".join(out) or "green"


def feed_status(feed: dict, repo: str, number: int) -> tuple[str, bool]:
    """Return ('as_of=... <status>', active) for one PR from the status feed."""
    live = feed.get("live")

    def entries(key: str) -> list:
        v = live.get(key) if isinstance(live, dict) else None
        return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []

    st, active = "idle", False
    for a in entries("active"):
        if a.get("repo") == repo and a.get("number") == number:
            st, active = (
                f"ACTIVE sha={str(a.get('sha') or '')[:9]} started={a.get('started_at')} "
                f"phase={a.get('phase')} progress={a.get('progress')}",
                True,
            )
    if not active:
        for q in entries("queued"):
            if q.get("repo") == repo and q.get("number") == number:
                st = (
                    f"queued sha={str(q.get('sha') or '')[:9]} reason={q.get('reason')} "
                    f"eligible_at={q.get('eligible_at')}"
                )
                break
    return f"as_of={feed.get('data_as_of')} {st}", active


def gate_comment(comments: list, bot: str, marker: str) -> Optional[tuple[str, str]]:
    """Return (updated_at, first non-blank line) of the bot's newest-edited gate comment."""
    best = None
    for c in comments:
        body = c.get("body") or ""
        if c.get("login") != bot or marker not in body:
            continue
        text = re.sub(r"<!--.*?-->", "", body, flags=re.S).replace("\r", "")
        line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
        ts = c.get("updated_at") or ""
        if best is None or (parse_ts(ts) or EPOCH) > (parse_ts(best[0]) or EPOCH):
            best = (ts, line)
    return best


def is_reviewing(
    feed_active: bool,
    feed_as_of: Optional[str],
    gate: Optional[tuple[str, str]],
    busy_re: str,
) -> bool:
    if gate and re.search(busy_re, gate[1]):
        return True
    if not feed_active:
        return False
    # A gate edit after the feed snapshot overrides a stale ACTIVE.
    g, f = parse_ts(gate[0]) if gate else None, parse_ts(feed_as_of)
    return not (g and f and g > f)


# --- GitHub-backed reader -----------------------------------------------------


class Watcher:
    def __init__(
        self, args: argparse.Namespace, run: Runner = run_gh, fetch: Fetcher = fetch_url
    ) -> None:
        self.a, self.run, self.fetch = args, run, fetch
        self.owner, self.name = args.repo.split("/", 1)
        self.warned: dict = {}

    def warn(self, n: int, msg: str) -> None:
        """Report a failed fetch on stderr, once per PR per distinct error."""
        if self.warned.get(n) != msg:
            self.warned[n] = msg
            print(f"pr_watch: PR{n}: {msg}", file=sys.stderr, flush=True)

    def gate(self, n: int, feed: bool = True) -> Optional[tuple[str, str, bool]]:
        """Return (feed line, gate line, reviewing); None on a fetch failure."""
        a = self.a
        feed_url = feed and getattr(a, "gate_feed_url", None)
        feed_line, active, as_of = "off", False, None
        if feed_url:
            feed_line = "unavailable"
            raw = self.fetch(feed_url)
            try:
                data = json.loads(raw) if raw else None
            except ValueError:
                data = None
            if isinstance(data, dict):
                feed_line, active = feed_status(data, a.repo, n)
                as_of = data.get("data_as_of")
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
            comments = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
        except ValueError:
            rc, err = 1, "unparseable comments response"
        if rc != 0:
            self.warn(n, "comments: " + first_line(err))
            return None
        g = gate_comment(comments, a.gate_bot, a.gate_marker or f"{a.gate_bot}-gate")
        gate_line = f"{g[0]} {g[1]}" if g else "none"
        busy = getattr(a, "gate_busy", DEFAULT_BUSY)
        return feed_line, gate_line, is_reviewing(active, as_of, g, busy)

    def reading(self, n: int) -> Optional[str]:
        a = self.a
        rc, out, err = self.run(
            [
                "api",
                "graphql",
                "-f",
                f"query={THREADS_QUERY}",
                "-f",
                f"o={self.owner}",
                "-f",
                f"r={self.name}",
                "-F",
                f"n={n}",
                "--jq",
                ".data.repository.pullRequest",
            ]
        )
        try:
            pr = json.loads(out) if rc == 0 else None
        except ValueError:
            pr = None
        if not isinstance(pr, dict):
            self.warn(n, "pull request: " + first_line(err))
            return None
        head, state = summarize_pr(pr)
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
    prev: dict = {}
    passes = 0
    while True:
        changed = False
        for n in prs:
            try:
                cur = w.reading(n)
            except Exception as e:  # malformed response: a failed reading
                w.warn(n, f"{type(e).__name__}: {e}")
                cur = None
            if cur is None or cur == prev.get(n):
                continue
            w.warned.pop(n, None)
            if not w.a.quiet_init or n in prev:
                print(f"PR{n} {cur}", file=out, flush=True)
                changed = True
            prev[n] = cur
        passes += 1
        if (w.a.oneshot and changed) or (max_passes and passes >= max_passes):
            return 0
        sleep(w.a.interval)


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
        help="running checks, pending reviews, a new head and a green "
        "build are not changes",
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
        "--interval", type=float, default=120.0, help="seconds between passes"
    )
    g = sub.add_parser("gate", parents=[common], help="is the gate bot reviewing now")
    g.add_argument("pr", type=int)
    g.add_argument(
        "--gate-feed-url",
        default=os.environ.get("GATE_FEED_URL"),
        help="JSON status feed of the bot's running reviews",
    )
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
    return EXIT_REVIEWING if g[2] else EXIT_IDLE


if __name__ == "__main__":
    sys.exit(main())
