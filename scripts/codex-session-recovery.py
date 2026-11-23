#!/usr/bin/env python3
"""Read-only, bounded SessionStart reminder for interrupted Codex dispatches."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import stat
import sys
from typing import Any


BUDGET_SECS = 3
JSON_LIMIT = 1024 * 1024
MAX_ORPHANS = 5
ACTIVE_STATUSES = ("running", "queued", "pending")


def read_json(path: Path) -> Any:
    """Ignore malformed, oversized, or non-regular state files."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open("rb") as stream:
            data = stream.read(JSON_LIMIT + 1)
        return json.loads(data) if len(data) <= JSON_LIMIT else None
    except (OSError, ValueError, RecursionError):
        return None


def pid_alive(pid: Any) -> bool:
    """Only a populated positive PID proven absent counts as orphaned."""
    if type(pid) is not int or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        pass
    return True


def recovery_context(payload: dict, env: dict) -> str:
    """Describe this session's active jobs and the exact watchdog invocation."""
    if not isinstance(payload, dict) or payload.get("source") not in (
        "resume",
        "compact",
    ):
        return ""
    session = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session, str) or not session or not isinstance(cwd, str):
        return ""
    if not Path(cwd).is_absolute() or "\0" in cwd:
        return ""
    home = Path(env.get("HOME", str(Path.home())))
    worktrees = Path(env.get("CLAUDIUS_WORKTREE_ROOT", "/data/git-worktrees"))
    cwd_path = Path(cwd).resolve()
    slug = (
        cwd_path.name
        if cwd_path.parent == worktrees.resolve()
        else cwd.strip("/").replace("/", "-")
    )
    owned = set()
    try:
        for path in worktrees.iterdir():
            if (
                (path.name == slug or path.name.startswith(slug + "-"))
                and (path / ".git").exists()
                and path.is_dir()
            ):
                owned.add(path.resolve())
    except OSError:
        pass
    roots = [home / ".claude/plugins/data/codex-openai-codex/state"]
    if env.get("CLAUDE_PLUGIN_DATA"):
        roots.append(Path(env["CLAUDE_PLUGIN_DATA"]) / "state")
    temp = next((env[key] for key in ("TMPDIR", "TMP", "TEMP") if env.get(key)), "/tmp")
    roots.append(Path(temp) / "codex-companion")
    active = False
    orphans = []
    orphan_count = 0
    monitor_env: list[str] = []
    for root in dict.fromkeys(roots):
        for path in root.glob("*/jobs/*.json"):
            job = read_json(path)
            if not isinstance(job, dict) or job.get("status") not in ACTIVE_STATUSES:
                continue
            workspace = job.get("workspaceRoot")
            if not isinstance(workspace, str) or not workspace or "\0" in workspace:
                continue
            try:
                workspace_path = Path(workspace).resolve()
            except (OSError, ValueError, RuntimeError):
                continue
            job_session = job.get("sessionId")
            if job_session != session and workspace_path not in owned:
                if job_session or workspace_path != cwd_path:
                    continue
            if not active:
                monitor_env = [
                    "env",
                    (
                        f"CLAUDE_PLUGIN_DATA={root.parent}"
                        if root.name == "state"
                        else "CLAUDE_PLUGIN_DATA="
                    ),
                ]
                if root.name != "state":
                    monitor_env.append(f"TMPDIR={root.parent}")
            active = True
            if pid_alive(job.get("pid")):
                continue
            orphan_count += 1
            if len(orphans) < MAX_ORPHANS:
                orphans.append(
                    f"Codex orphan job={json.dumps(job.get('id', path.stem))} "
                    f"status={job['status']} pid={job['pid']} --cwd {shlex.quote(workspace)}"
                )
    if not active and not owned:
        return ""
    lines = orphans
    if orphan_count > MAX_ORPHANS:
        lines.append(
            f"+{orphan_count - MAX_ORPHANS} more orphaned jobs; inspect jobs/*.json."
        )
    if orphan_count:
        lines.append(
            'Recovery: from each job\'s cwd run node "$CODEX_ROOT/scripts/codex-companion.mjs" '
            "cancel <job-id> --json; confirm status --all is no longer running, "
            "then redispatch task --resume-last with the identical --cwd. "
            "See delegate/references/codex-sandbox-and-recovery.md."
        )
    command = shlex.join(
        [
            *monitor_env,
            "python3",
            str(Path(__file__).with_name("minion-monitoring.py").resolve()),
            "--session-id",
            session,
            "--stall-secs",
            "300",
            "--worktrees",
            str(worktrees),
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
