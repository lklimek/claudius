"""Tests for the deterministic per-checkout task ledger."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "task-ledger.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("task_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_ledger = _load_module()


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every test out of the user's real state directory."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("CLAUDIUS_STATE_DIR", str(state_dir))
    return state_dir


def _ledger_data() -> tuple[Path, dict]:
    path = task_ledger.ledger_path()
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


def test_path_is_deterministic_and_checkout_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_state_dir: Path
) -> None:
    first_root = tmp_path / "first" / "Same Repo"
    second_root = tmp_path / "second" / "Same Repo"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    monkeypatch.setattr(task_ledger, "_checkout_root", lambda: str(first_root))
    first = task_ledger.ledger_path()
    repeated = task_ledger.ledger_path()
    monkeypatch.setattr(task_ledger, "_checkout_root", lambda: str(second_root))
    second = task_ledger.ledger_path()

    assert first == repeated
    assert first != second
    assert first.parent == isolated_state_dir / "tasks"
    assert second.parent == isolated_state_dir / "tasks"
    assert re.fullmatch(r"same-repo-[0-9a-f]{12}\.yaml", first.name)
    assert re.fullmatch(r"same-repo-[0-9a-f]{12}\.yaml", second.name)


def test_non_repo_path_falls_back_to_real_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_state_dir: Path
) -> None:
    checkout = tmp_path / "Not A Repo"
    checkout.mkdir()
    monkeypatch.chdir(checkout)

    path = task_ledger.ledger_path()

    root = os.path.realpath(checkout)
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    assert path == isolated_state_dir / "tasks" / f"not-a-repo-{digest}.yaml"


def test_state_directory_environment_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)

    explicit = tmp_path / "explicit"
    xdg = tmp_path / "xdg"
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDIUS_STATE_DIR", str(explicit))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    assert task_ledger.ledger_path().parent == explicit / "tasks"

    monkeypatch.delenv("CLAUDIUS_STATE_DIR")
    assert task_ledger.ledger_path().parent == xdg / "claudius" / "tasks"

    monkeypatch.delenv("XDG_STATE_HOME")
    assert task_ledger.ledger_path().parent == (
        home / ".local" / "state" / "claudius" / "tasks"
    )


def test_add_creates_canonical_ledger_and_assigns_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["add", "Design ledger"]) == 0
    assert capsys.readouterr().out == "t1\n"
    assert (
        task_ledger.main(
            [
                "add",
                "Implement ledger",
                "--owner",
                "bilby",
                "--note",
                "Keep it deterministic",
                "--blocked-by",
                "t1, external-id",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "t2\n"

    path, data = _ledger_data()
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith(
        "# Claudius task ledger (managed by scripts/task-ledger.py).\n"
        "# Deterministic per-checkout path"
    )
    assert "schema: 1\n" in raw
    assert data["schema"] == 1
    assert data["checkout"] == os.path.realpath(REPO_ROOT)
    assert [task["id"] for task in data["tasks"]] == ["t1", "t2"]
    assert data["tasks"][0]["owner"] is None
    assert data["tasks"][1]["owner"] == "bilby"
    assert data["tasks"][1]["note"] == "Keep it deterministic"
    assert data["tasks"][1]["blocked_by"] == ["t1", "external-id"]


def test_id_assignment_skips_nonconforming_hand_edited_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["add", "First"]) == 0
    capsys.readouterr()
    path, data = _ledger_data()
    data["tasks"].append(
        {
            "id": "manual",
            "title": "Hand edited",
            "status": "pending",
            "owner": None,
            "note": "",
            "blocked_by": [],
            "created": data["updated"],
            "updated": data["updated"],
        }
    )
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert task_ledger.main(["add", "Second"]) == 0
    assert capsys.readouterr().out == "t2\n"


def test_update_changes_fields_and_bumps_timestamps(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    timestamps = iter(["2026-07-15T19:10:00Z", "2026-07-15T19:11:00Z"])
    monkeypatch.setattr(task_ledger, "_utc_now", lambda: next(timestamps))
    assert task_ledger.main(["add", "Original"]) == 0
    capsys.readouterr()

    assert (
        task_ledger.main(
            [
                "update",
                "t1",
                "--title",
                "Changed",
                "--owner",
                "claudius",
                "--note",
                "Ready",
                "--status",
                "blocked",
                "--blocked-by",
                "t9,t10",
            ]
        )
        == 0
    )
    _, data = _ledger_data()
    task = data["tasks"][0]
    assert task["title"] == "Changed"
    assert task["owner"] == "claudius"
    assert task["note"] == "Ready"
    assert task["status"] == "blocked"
    assert task["blocked_by"] == ["t9", "t10"]
    assert task["created"] == "2026-07-15T19:10:00Z"
    assert task["updated"] == "2026-07-15T19:11:00Z"
    assert data["updated"] == "2026-07-15T19:11:00Z"


def test_update_unknown_id_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["update", "missing", "--title", "Nope"]) != 0
    captured = capsys.readouterr()
    assert "missing" in captured.err


def test_done_and_start_set_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["add", "Transition me"]) == 0
    capsys.readouterr()
    assert task_ledger.main(["done", "t1"]) == 0
    assert _ledger_data()[1]["tasks"][0]["status"] == "done"
    assert task_ledger.main(["start", "t1"]) == 0
    assert _ledger_data()[1]["tasks"][0]["status"] == "in_progress"


def test_list_filters_and_formats_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["add", "Pending work"]) == 0
    capsys.readouterr()
    assert task_ledger.main(["add", "Finished work", "--status", "done"]) == 0
    capsys.readouterr()

    assert task_ledger.main(["list"]) == 0
    plain = capsys.readouterr().out
    assert "Pending work" in plain
    assert "Finished work" not in plain

    assert task_ledger.main(["list", "--all"]) == 0
    all_tasks = capsys.readouterr().out
    assert "Pending work" in all_tasks
    assert "Finished work" in all_tasks

    assert task_ledger.main(["list", "--status", "done"]) == 0
    filtered = capsys.readouterr().out
    assert "Pending work" not in filtered
    assert "Finished work" in filtered

    assert task_ledger.main(["list", "--all", "--format", "md"]) == 0
    markdown = capsys.readouterr().out
    assert "- [ ] t1 (pending) Pending work" in markdown
    assert "- [x] t2 (done) Finished work" in markdown


def test_list_yaml_and_empty_ledger_are_friendly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["list", "--format", "yaml"]) == 0
    assert "no tasks" in capsys.readouterr().out.lower()

    assert task_ledger.main(["add", "Serializable"]) == 0
    capsys.readouterr()
    assert task_ledger.main(["list", "--format", "yaml"]) == 0
    tasks = yaml.safe_load(capsys.readouterr().out)
    assert [task["title"] for task in tasks] == ["Serializable"]


@pytest.mark.parametrize("command", ["add", "update"])
def test_invalid_status_is_rejected(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    if command == "update":
        assert task_ledger.main(["add", "Existing"]) == 0
        capsys.readouterr()
        argv = ["update", "t1", "--status", "invalid"]
    else:
        argv = ["add", "Invalid", "--status", "invalid"]

    with pytest.raises(SystemExit) as error:
        task_ledger.main(argv)
    assert error.value.code != 0


def test_remove_deletes_task_and_unknown_id_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert task_ledger.main(["add", "Disposable"]) == 0
    capsys.readouterr()
    assert task_ledger.main(["remove", "t1"]) == 0
    assert _ledger_data()[1]["tasks"] == []
    assert task_ledger.main(["remove", "t1"]) != 0
    assert "t1" in capsys.readouterr().err


def test_malformed_yaml_errors_without_clobbering(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = task_ledger.ledger_path()
    malformed = "schema: [unterminated\n"
    path.write_text(malformed, encoding="utf-8")

    assert task_ledger.main(["list"]) != 0
    captured = capsys.readouterr()
    assert str(path) in captured.err
    assert path.read_text(encoding="utf-8") == malformed


def test_path_cli_smoke_does_not_create_ledger(
    tmp_path: Path, isolated_state_dir: Path
) -> None:
    checkout = tmp_path / "cli-checkout"
    checkout.mkdir()
    environment = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "path"],
        cwd=checkout,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip())
    assert path.parent == isolated_state_dir / "tasks"
    assert path.parent.is_dir()
    assert not path.exists()
