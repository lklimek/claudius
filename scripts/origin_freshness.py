#!/usr/bin/env python3
"""SessionStart probe: tell the session when the ground under its branch has moved.

Wired as a sibling SessionStart hook (see ``hooks/hooks.json``), separate from
``hooks/session-start.sh`` so a slow remote can never starve that hook's
Source-of-Truth injection.

Two independent kinds of staleness, reported together and deduped when they are
the same ref:

* **base** — the branch this one was cut from has gained commits since the merge
  base. This is the signal that matters: a feature branch perfectly in sync with
  its own upstream can still be sitting on a base that has moved three PRs ahead,
  and nothing surfaces that until merge time.
* **upstream** — the current branch's own upstream gained commits, i.e. someone
  else pushed to this branch.

Both are counted with ``HEAD..<ref>`` (merge-base semantics): "behind <ref>" is
the actionable statement, "diverged from <ref>" is not.

Contract — fail open, fail silent. Detached HEAD, no configured upstream, no such
remote, an unreachable/auth-failing remote, no repository, no git binary, or any
unexpected error all produce zero output, zero delay past the budget below, and
exit 0. A checkout that is current is equally silent: only divergence is worth a
session's tokens.

Read-only with respect to the checkout: the single fetch updates only the two
remote-tracking refs named in its refspecs. The index, working tree, checked-out
branch and local branches are never touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Callable, Optional

# Time bounds. TOTAL_BUDGET_SEC is a hard ceiling across every git call and must
# stay strictly under the hook's declared timeout in hooks/hooks.json (10s), so
# the probe always reaches its own quiet exit instead of being killed mid-write.
# FETCH_TIMEOUT_SEC covers the one and only network call — both refs travel in a
# single fetch — which is a warm two-ref fetch on an ordinary link; an offline or
# unroutable remote fails DNS/connect long before it, and a session start is not
# allowed to feel stalled for longer than this. Everything else is local git,
# milliseconds each.
TOTAL_BUDGET_SEC = 8.0
FETCH_TIMEOUT_SEC = 5.0
LOCAL_TIMEOUT_SEC = 3.0

MAX_COMMITS = 10
MAX_PATHS = 25

# Fallback base names, in order, when refs/remotes/<remote>/HEAD is absent.
BASE_CANDIDATES = ("main", "master")

GitRun = Callable[[list, float], Optional[str]]


def git_env(base: dict) -> dict:
    """git environment that can never block on an interactive credential prompt.

    A timeout alone is not enough: a prompting remote would burn the whole budget
    before failing. ``echo`` as askpass hands git an empty secret so auth fails
    immediately. A user-set ``GIT_SSH_COMMAND`` is preserved — it may be the only
    way the host is reachable at all.
    """
    env = dict(base)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["SSH_ASKPASS"] = "echo"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


class DeadlineGitRunner:
    """Runs git under one shared deadline, returning None on any failure."""

    def __init__(
        self,
        budget: float = TOTAL_BUDGET_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._deadline = clock() + budget
        self._env = git_env(os.environ)

    def __call__(self, args: list, timeout: float) -> Optional[str]:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            return None
        try:
            proc = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=min(timeout, remaining),
                env=self._env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None


def _line(output: Optional[str]) -> str:
    """First line of a git output, or "" when the call failed or said nothing."""
    return output.strip().splitlines()[0] if output and output.strip() else ""


def _strip_prefix(value: str, prefix: str) -> str:
    """``str.removeprefix``, which is 3.9-incompatible."""
    return value[len(prefix) :] if value.startswith(prefix) else value


def _count(output: Optional[str]) -> int:
    """Parse ``rev-list --count`` output; anything unusable counts as zero."""
    text = _line(output)
    return int(text) if text.isdigit() else 0


def _resolve_base(run: GitRun, remote: str) -> str:
    """Short name of the remote's default branch, or "" — strictly offline.

    ``refs/remotes/<remote>/HEAD`` is set by clone and is authoritative. Without
    it, a remote-tracking ref for a conventional default name is the best offline
    guess. Asking a forge API instead would put auth and a second network round
    trip on a path whose entire contract is "never hang".
    """
    head = _line(
        run(
            ["symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"],
            LOCAL_TIMEOUT_SEC,
        )
    )
    if head:
        return _strip_prefix(head, f"refs/remotes/{remote}/")
    for candidate in BASE_CANDIDATES:
        ref = f"refs/remotes/{remote}/{candidate}"
        if _line(run(["rev-parse", "--verify", "--quiet", ref], LOCAL_TIMEOUT_SEC)):
            return candidate
    return ""


def _section(run: GitRun, kind: str, remote: str, short: str) -> Optional[dict]:
    """Divergence detail for one tracking ref, or None when HEAD is not behind it."""
    ref = f"refs/remotes/{remote}/{short}"
    behind = _count(run(["rev-list", "--count", f"HEAD..{ref}"], LOCAL_TIMEOUT_SEC))
    if behind <= 0:
        return None
    log = run(
        [
            "log",
            "--no-color",
            f"--max-count={MAX_COMMITS}",
            "--format=%h %s",
            f"HEAD..{ref}",
        ],
        LOCAL_TIMEOUT_SEC,
    )
    diff = run(["diff", "--name-only", f"HEAD...{ref}"], LOCAL_TIMEOUT_SEC)
    paths = [path for path in (diff or "").splitlines() if path]
    return {
        "kind": kind,
        "ref": f"{remote}/{short}",
        "behind": behind,
        "commits": [line for line in (log or "").splitlines() if line],
        "paths": paths[:MAX_PATHS],
        "hidden_paths": max(0, len(paths) - MAX_PATHS),
    }


def freshness_report(run: GitRun) -> Optional[dict]:
    """Staleness facts for the current branch, or None when there is nothing to say."""
    branch = _line(
        run(["symbolic-ref", "--quiet", "--short", "HEAD"], LOCAL_TIMEOUT_SEC)
    )
    if not branch:
        return None

    remote = _line(
        run(["config", "--get", f"branch.{branch}.remote"], LOCAL_TIMEOUT_SEC)
    )
    if not remote:
        return None
    merge_ref = _line(
        run(["config", "--get", f"branch.{branch}.merge"], LOCAL_TIMEOUT_SEC)
    )
    if not merge_ref:
        return None

    # Membership test rather than `remote get-url`: it also rejects a local-only
    # upstream ("."), and settles the missing-remote case without a network call.
    remotes = run(["remote"], LOCAL_TIMEOUT_SEC)
    if remotes is None or remote not in remotes.split():
        return None

    upstream_short = _strip_prefix(merge_ref, "refs/heads/")
    base_short = _resolve_base(run, remote)

    # One network call for both refs. Explicit refspecs keep the write surface to
    # exactly these remote-tracking refs, and the destinations are the same names
    # read back below, so the comparison never depends on the remote's configured
    # fetch refspec. A base branch deleted upstream fails the whole fetch and the
    # probe goes quiet — fail-open, and preferable to a second network call.
    refspecs = [f"+refs/heads/{upstream_short}:refs/remotes/{remote}/{upstream_short}"]
    if base_short and base_short != upstream_short:
        refspecs.append(f"+refs/heads/{base_short}:refs/remotes/{remote}/{base_short}")
    if (
        run(
            ["fetch", "--quiet", "--no-tags", "--", remote, *refspecs],
            FETCH_TIMEOUT_SEC,
        )
        is None
    ):
        return None

    sections = []
    if base_short:
        sections.append(_section(run, "base", remote, base_short))
    if base_short != upstream_short:
        sections.append(_section(run, "upstream", remote, upstream_short))
    sections = [section for section in sections if section]
    if not sections:
        return None
    return {"branch": branch, "sections": sections}


HEADINGS = {
    "base": ("## Base branch has moved", "the base"),
    "upstream": ("## Branch upstream has moved", "the upstream"),
}


def _render(branch: str, section: dict) -> list:
    heading, subject = HEADINGS[section["kind"]]
    behind, ref = section["behind"], section["ref"]
    plural = "" if behind == 1 else "s"
    who = (
        " — someone else pushed to this branch" if section["kind"] == "upstream" else ""
    )
    lines = [heading, "", f"`{branch}` is {behind} commit{plural} behind `{ref}`{who}."]
    if section["commits"]:
        lines += ["", f"New commits on {subject}:"]
        lines += [f"- {commit}" for commit in section["commits"]]
        if behind > len(section["commits"]):
            lines.append(f"- ...and {behind - len(section['commits'])} more")
    if section["paths"]:
        lines += ["", f"Files changed on {subject} since the fork point:"]
        lines += [f"- {path}" for path in section["paths"]]
        if section["hidden_paths"]:
            lines.append(f"- ...and {section['hidden_paths']} more files")
    return lines


def format_context(report: dict) -> str:
    """Render the divergence as SessionStart additionalContext."""
    branch, sections = report["branch"], report["sections"]
    lines = []
    for section in sections:
        if lines:
            lines.append("")
        lines += _render(branch, section)
    lines += [
        "",
        "Before planning: read the commits above that touch the files this task will "
        f"touch (`git log -p HEAD..{sections[0]['ref']} -- <path>`) — the count alone is "
        "not actionable. Rebase, or fold the overlap into the plan.",
    ]
    return "\n".join(lines)


def main(run: Optional[GitRun] = None) -> int:
    """Emit the SessionStart payload when behind; otherwise say nothing. Always 0."""
    try:
        report = freshness_report(run or DeadlineGitRunner())
        if report is None:
            return 0
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": format_context(report),
                }
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
    except Exception:  # a session-start probe never breaks the session
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
