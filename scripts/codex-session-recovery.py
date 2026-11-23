#!/usr/bin/env python3
"""Bounded SessionStart recovery for orphaned Codex jobs.

Upstream worker-death/reconciliation defects:
https://github.com/openai/codex-plugin-cc/issues/432
https://github.com/openai/codex-plugin-cc/issues/377
"""

from __future__ import annotations

import heapq
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import sys
import time
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "claudius_minion_monitoring", PLUGIN_ROOT / "scripts/minion-monitoring.py"
)
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = watchdog
SPEC.loader.exec_module(watchdog)

BUDGET_SECS = 3
JSON_LIMIT = 1024 * 1024
MAX_ORPHANS = 5
MAX_SCAN_JOBS = 256
METADATA_BUDGET_SECS = 0.5
PROC_ROOT = Path("/proc")


def read_json(path: Path) -> Any:
    """Keep startup reads smaller than the long-lived monitor's cached reads."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open("rb") as stream:
            data = stream.read(JSON_LIMIT + 1)
        return json.loads(data) if len(data) <= JSON_LIMIT else None
    except (OSError, ValueError, RecursionError):
        return None


def recent_jobs(root: Path, now: float) -> list[Path]:
    """Bound metadata time and JSON reads, prioritising recent job activity."""
    newest: list[tuple[float, Path]] = []
    deadline = time.monotonic() + METADATA_BUDGET_SECS
    for path in root.glob("*/jobs/*.json"):
        if time.monotonic() >= deadline:
            break
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < now - watchdog.DEFAULT_JOB_RECENCY_SECS:
            continue
        heapq.heappush(newest, (mtime, path))
        if len(newest) > MAX_SCAN_JOBS:
            heapq.heappop(newest)
    return [path for _, path in sorted(newest, reverse=True)]


def printable(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 4096 and value.isprintable()


def recovery_context(payload: dict, env: dict) -> str:
    """Describe only active jobs belonging to the resumed session."""
    if not isinstance(payload, dict) or payload.get("source") not in (
        "resume",
        "compact",
    ):
        return ""
    session = payload.get("session_id")
    cwd = payload.get("cwd")
    if not printable(session) or not watchdog.SAFE_FIELD.fullmatch(session):
        return ""
    if not printable(cwd) or not Path(cwd).is_absolute():
        return ""
    worktrees = env.get("CLAUDIUS_WORKTREE_ROOT", str(watchdog.DEFAULT_WORKTREE_ROOT))
    if not printable(worktrees) or not Path(worktrees).is_absolute():
        return ""
    cwd_path = Path(cwd)
    slug = (
        cwd_path.name
        if cwd_path.parent == Path(worktrees)
        else cwd.strip("/").replace("/", "-")
    )
    proc = watchdog.ProcInspector(PROC_ROOT)
    active = False
    orphans = []
    orphan_count = 0
    try:
        for path in recent_jobs(watchdog.codex_state_root(env), time.time()):
            job = read_json(path)
            if not isinstance(job, dict):
                continue
            status = job.get("status")
            if not isinstance(status, str) or status not in watchdog.ACTIVE_STATUSES:
                continue
            job_id = job.get("id")
            if (
                not isinstance(job_id, str)
                or len(job_id) > 64
                or not job_id[:1].isalnum()
                or not watchdog.SAFE_FIELD.fullmatch(job_id)
            ):
                continue
            workspace = job.get("workspaceRoot")
            if not printable(workspace) or not Path(workspace).is_absolute():
                continue
            job_session = job.get("sessionId")
            if job_session not in (None, "") and job_session != session:
                continue
            if job_session in (None, "") and workspace != cwd:
                continue
            active = True
            if proc.launcher(job.get("pid"), Path(workspace)) != "dead":
                continue
            orphan_count += 1
            if len(orphans) < MAX_ORPHANS:
                orphans.append(
                    f"Codex orphan job={shlex.quote(job_id)} status={status} "
                    f"pid={job['pid']} --cwd {shlex.quote(workspace)}"
                )
    except DeadlineExpired:
        pass
    if not active:
        return ""
    lines = orphans
    if orphan_count > MAX_ORPHANS:
        lines.append(
            f"+{orphan_count - MAX_ORPHANS} more orphaned jobs; inspect jobs/*.json."
        )
    if orphan_count:
        reference = (
            PLUGIN_ROOT / "skills/delegate/references/codex-sandbox-and-recovery.md"
        )
        lines.append(
            f"Recovery: read {shlex.quote(str(reference))} (cancel, then --resume-last with identical --cwd)."
        )
    command = shlex.join(
        [
            "python3",
            str(PLUGIN_ROOT / "scripts/minion-monitoring.py"),
            "--session-id",
            session,
            "--stall-secs",
            "300",
            "--worktrees",
            worktrees,
            "--worktrees-session-filter",
            slug,
        ]
    )
    lines.append(
        "Re-arm one stall watchdog if none is running (30-minute cap; re-arm on expiry "
        "only while dispatched work is live):\n"
        f'Monitor(timeout_ms=1800000, description="agent stall watchdog", '
        f"command={json.dumps(command)})"
    )
    return "\n".join(lines)


class DeadlineExpired(Exception):
    """Escape filesystem error handlers when the hook budget expires."""


def _timeout(*_) -> None:
    raise DeadlineExpired("recovery deadline")


def main() -> int:
    """Never delay or fail session start when state or input is unavailable."""
    signal.signal(signal.SIGALRM, _timeout)
    signal.setitimer(signal.ITIMER_REAL, BUDGET_SECS)
    try:
        payload = json.loads(sys.stdin.read(JSON_LIMIT + 1))
        context = recovery_context(payload, dict(os.environ))
        if context:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": context,
                        }
                    }
                )
            )
    except Exception:
        pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
