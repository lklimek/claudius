#!/usr/bin/env python3
"""Manage a durable, deterministic, per-checkout task ledger."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

STATUSES = ("pending", "in_progress", "blocked", "done", "cancelled")
HIDDEN_STATUSES = {"done", "cancelled"}
HEADER = """\
# Claudius task ledger (managed by scripts/task-ledger.py).
# Deterministic per-checkout path — recompute anytime with:
#   python3 scripts/task-ledger.py path
# Safe to hand-edit; the script re-emits this header on write.
"""
TASK_ID_PATTERN = re.compile(r"^t(\d+)$")
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class LedgerError(Exception):
    """Report an expected task-ledger failure to the CLI."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_base_dir() -> Path:
    explicit = os.environ.get("CLAUDIUS_STATE_DIR")
    if explicit:
        return Path(os.path.abspath(explicit))

    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        state_home = Path(os.path.abspath(xdg_state))
    else:
        state_home = Path(os.path.abspath(os.path.expanduser("~/.local/state")))
    return state_home / "claudius"


def _checkout_root() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        root = result.stdout.strip() if result.returncode == 0 else os.getcwd()
        if not root:
            root = os.getcwd()
    except (OSError, subprocess.SubprocessError):
        root = os.getcwd()
    return os.path.realpath(root)


def _slug(root: str) -> str:
    slug = SLUG_PATTERN.sub("-", os.path.basename(root).lower()).strip("-")
    return slug or "root"


def _ledger_path(root: str) -> Path:
    root = os.path.realpath(root)
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    tasks_dir = _state_base_dir() / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir / f"{_slug(root)}-{digest}.yaml"


def ledger_path() -> Path:
    """Return the deterministic ledger path and create its parent directory."""
    return _ledger_path(_checkout_root())


def _require_yaml() -> None:
    if yaml is None:
        raise LedgerError(
            "PyYAML is required; install it with: sudo apt-get install python3-yaml"
        )


def _empty_ledger(root: str) -> dict[str, Any]:
    return {"schema": 1, "checkout": root, "updated": "", "tasks": []}


def _validate_ledger(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise LedgerError(f"Invalid task ledger {path}: expected a YAML mapping")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise LedgerError(f"Invalid task ledger {path}: 'tasks' must be a list")
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            raise LedgerError(
                f"Invalid task ledger {path}: task {index} must be a mapping"
            )
        status = task.get("status")
        if status not in STATUSES:
            raise LedgerError(
                f"Invalid task ledger {path}: task {task.get('id', index)!r} "
                f"has invalid status {status!r}"
            )
    return data


def _load_ledger(path: Path, root: str) -> dict[str, Any]:
    _require_yaml()
    if not path.exists():
        return _empty_ledger(root)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise LedgerError(f"Could not parse task ledger {path}: {error}") from error
    return _validate_ledger(data, path)


def _canonical_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title", ""),
        "status": task.get("status", "pending"),
        "owner": task.get("owner"),
        "note": task.get("note", ""),
        "blocked_by": task.get("blocked_by", []),
        "created": task.get("created", ""),
        "updated": task.get("updated", ""),
    }


def _write_ledger(path: Path, root: str, ledger: dict[str, Any]) -> None:
    _require_yaml()
    canonical = {
        "schema": 1,
        "checkout": root,
        "updated": ledger["updated"],
        "tasks": [_canonical_task(task) for task in ledger["tasks"]],
    }
    body = yaml.safe_dump(
        canonical,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(HEADER)
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
        raise LedgerError(f"Could not write task ledger {path}: {error}") from error


def _parse_blocked_by(value: str | None) -> list[str]:
    if value is None:
        return []
    return [task_id.strip() for task_id in value.split(",") if task_id.strip()]


def _next_task_id(tasks: list[dict[str, Any]]) -> str:
    suffixes = []
    for task in tasks:
        match = TASK_ID_PATTERN.fullmatch(str(task.get("id", "")))
        if match:
            suffixes.append(int(match.group(1)))
    return f"t{max(suffixes, default=0) + 1}"


def _find_task(ledger: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in ledger["tasks"]:
        if task.get("id") == task_id:
            return task
    raise LedgerError(f"Unknown task id: {task_id}")


def _read_current() -> tuple[Path, str, dict[str, Any]]:
    root = _checkout_root()
    path = _ledger_path(root)
    return path, root, _load_ledger(path, root)


def _save_current(
    path: Path, root: str, ledger: dict[str, Any], timestamp: str
) -> None:
    ledger["updated"] = timestamp
    _write_ledger(path, root, ledger)


def _add(args: argparse.Namespace) -> int:
    path, root, ledger = _read_current()
    timestamp = _utc_now()
    task_id = _next_task_id(ledger["tasks"])
    ledger["tasks"].append(
        {
            "id": task_id,
            "title": args.title,
            "status": args.status,
            "owner": args.owner,
            "note": args.note,
            "blocked_by": _parse_blocked_by(args.blocked_by),
            "created": timestamp,
            "updated": timestamp,
        }
    )
    _save_current(path, root, ledger, timestamp)
    print(task_id)
    return 0


def _update(args: argparse.Namespace) -> int:
    path, root, ledger = _read_current()
    task = _find_task(ledger, args.task_id)
    for field in ("status", "owner", "note", "title"):
        value = getattr(args, field)
        if value is not None:
            task[field] = value
    if args.blocked_by is not None:
        task["blocked_by"] = _parse_blocked_by(args.blocked_by)
    timestamp = _utc_now()
    task["updated"] = timestamp
    _save_current(path, root, ledger, timestamp)
    return 0


def _set_status(task_id: str, status: str) -> int:
    path, root, ledger = _read_current()
    task = _find_task(ledger, task_id)
    timestamp = _utc_now()
    task["status"] = status
    task["updated"] = timestamp
    _save_current(path, root, ledger, timestamp)
    return 0


def _render_plain(tasks: list[dict[str, Any]]) -> str:
    rows = [
        (
            str(task["id"]),
            str(task["status"]).upper(),
            str(task["owner"]) if task["owner"] is not None else "-",
            str(task["title"]),
        )
        for task in tasks
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    return "\n".join(
        f"{task_id:<{widths[0]}}  {status:<{widths[1]}}  {owner:<{widths[2]}}  {title}"
        for task_id, status, owner, title in rows
    )


def _render_markdown(tasks: list[dict[str, Any]]) -> str:
    lines = []
    for task in tasks:
        checked = "x" if task["status"] in HIDDEN_STATUSES else " "
        lines.append(f"- [{checked}] {task['id']} ({task['status']}) {task['title']}")
    return "\n".join(lines)


def _list(args: argparse.Namespace) -> int:
    _path, _root, ledger = _read_current()
    tasks = ledger["tasks"]
    if args.status:
        tasks = [task for task in tasks if task["status"] == args.status]
    elif not args.all:
        tasks = [task for task in tasks if task["status"] not in HIDDEN_STATUSES]

    if not tasks:
        print("No tasks.")
    elif args.format == "plain":
        print(_render_plain(tasks))
    elif args.format == "md":
        print(_render_markdown(tasks))
    else:
        print(
            yaml.safe_dump(
                [_canonical_task(task) for task in tasks],
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            end="",
        )
    return 0


def _remove(task_id: str) -> int:
    path, root, ledger = _read_current()
    task = _find_task(ledger, task_id)
    ledger["tasks"].remove(task)
    _save_current(path, root, ledger, _utc_now())
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Manage a durable per-checkout task ledger."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("path", help="Print the deterministic ledger path")

    add = subparsers.add_parser("add", help="Add a task")
    add.add_argument("title", help="Task title")
    add.add_argument("--status", choices=STATUSES, default="pending")
    add.add_argument("--owner")
    add.add_argument("--note", default="")
    add.add_argument("--blocked-by", help="Comma-separated task ids")

    update = subparsers.add_parser("update", help="Update a task")
    update.add_argument("task_id", metavar="id")
    update.add_argument("--status", choices=STATUSES)
    update.add_argument("--owner")
    update.add_argument("--note")
    update.add_argument("--title")
    update.add_argument("--blocked-by", help="Comma-separated task ids")

    for command, help_text in (
        ("done", "Mark a task done"),
        ("start", "Mark a task in progress"),
        ("remove", "Remove a task"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("task_id", metavar="id")

    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--all", action="store_true")
    list_parser.add_argument(
        "--format", choices=("plain", "md", "yaml"), default="plain"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the task-ledger command-line interface."""
    args = parse_args(argv)
    try:
        if args.command == "path":
            print(ledger_path())
            return 0
        if args.command == "add":
            return _add(args)
        if args.command == "update":
            return _update(args)
        if args.command == "done":
            return _set_status(args.task_id, "done")
        if args.command == "start":
            return _set_status(args.task_id, "in_progress")
        if args.command == "list":
            return _list(args)
        if args.command == "remove":
            return _remove(args.task_id)
    except LedgerError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
