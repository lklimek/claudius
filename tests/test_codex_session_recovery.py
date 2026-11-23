"""Isolated contracts for SessionStart Codex orphan recovery."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "codex-session-recovery.py"


@pytest.fixture
def recovery():
    spec = importlib.util.spec_from_file_location("codex_session_recovery", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def context(tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    env = {
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
        "CLAUDIUS_WORKTREE_ROOT": str(tmp_path / "worktrees"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "claudius-data"),
    }
    payload = {"session_id": "current-session", "cwd": str(cwd), "source": "resume"}
    return payload, env


def job(env, **fields):
    value = {
        "id": "orphan",
        "sessionId": "current-session",
        "status": "running",
        "workspaceRoot": "/worktree with spaces",
        "pid": 321,
        **fields,
    }
    path = (
        Path(env["HOME"])
        / ".claude/plugins/data/codex-openai-codex/state/workspace/jobs"
        / f"{value['id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("status", ["running", "queued", "pending"])
def test_dead_pid_reports_cancel_then_resume_with_same_cwd(
    recovery, context, monkeypatch, status
):
    payload, env = context
    path = job(env, status=status)
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    output = recovery.recovery_context(payload, env)
    assert "orphan" in output and "321" in output and status in output
    assert "/worktree with spaces" in output
    assert output.index("cancel") < output.index("--resume-last")
    assert "identical --cwd" in output
    assert "Monitor(timeout_ms=1800000" in output
    assert "--session-id current-session" in output
    assert "--worktrees-session-filter" in output
    assert "persistent=" not in output
    assert json.loads(path.read_text())["status"] == status


@pytest.mark.parametrize("pid", [777, None, 0, -1, True, "bad"])
def test_live_or_unknown_pid_only_reminds(recovery, context, monkeypatch, pid):
    payload, env = context
    job(env, pid=pid)
    monkeypatch.setattr(recovery, "pid_alive", lambda _: True)
    output = recovery.recovery_context(payload, env)
    assert "Monitor(" in output
    assert "cancel" not in output


def test_foreign_and_terminal_jobs_are_silent(recovery, context):
    payload, env = context
    job(env, id="foreign", sessionId="another-session", workspaceRoot=payload["cwd"])
    job(env, id="done", status="completed")
    assert recovery.recovery_context(payload, env) == ""


def test_missing_session_uses_workspace_scope(recovery, context, monkeypatch):
    payload, env = context
    job(env, id="local", sessionId=None, workspaceRoot=payload["cwd"])
    job(env, id="stranger", sessionId=None, workspaceRoot="/another/repo")
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    output = recovery.recovery_context(payload, env)
    assert "local" in output and "stranger" not in output


def test_worktree_discovery_uses_session_slug(recovery, context):
    payload, env = context
    worktrees = Path(env["CLAUDIUS_WORKTREE_ROOT"])
    unrelated = worktrees / "other-session-agent"
    unrelated.mkdir(parents=True)
    (unrelated / ".git").touch()
    assert recovery.recovery_context(payload, env) == ""
    slug = payload["cwd"].strip("/").replace("/", "-")
    selected = worktrees / f"{slug}-bilby"
    selected.mkdir()
    (selected / ".git").touch()
    output = recovery.recovery_context(payload, env)
    assert f"--worktrees-session-filter {slug}" in output
    assert "Monitor(" in output


def test_child_worktree_jobs_can_have_dispatcher_session(
    recovery, context, monkeypatch
):
    payload, env = context
    slug = payload["cwd"].strip("/").replace("/", "-")
    selected = Path(env["CLAUDIUS_WORKTREE_ROOT"]) / f"{slug}-bilby"
    selected.mkdir(parents=True)
    (selected / ".git").touch()
    job(env, sessionId="worker-session", workspaceRoot=str(selected))
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    assert "cancel" in recovery.recovery_context(payload, env)


def test_malformed_records_do_not_hide_valid_jobs(recovery, context, monkeypatch):
    payload, env = context
    path = job(env)
    for index, content in enumerate(["{", "[]", '{"status": []}', "null"]):
        (path.parent / f"bad-{index}.json").write_text(content)
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    assert "orphan" in recovery.recovery_context(payload, env)


def test_pid_probe_distinguishes_dead_from_permission_denied(recovery, monkeypatch):
    def dead(*_):
        raise ProcessLookupError

    monkeypatch.setattr(recovery.os, "kill", dead)
    assert recovery.pid_alive(321) is False

    def denied(*_):
        raise PermissionError

    monkeypatch.setattr(recovery.os, "kill", denied)
    assert recovery.pid_alive(321) is True
    for pid in (None, 0, -1, True, "321"):
        assert recovery.pid_alive(pid) is True


@pytest.mark.parametrize("raw", ["{", "[]", "{}", '{"source":"startup"}'])
def test_cli_fail_open_and_silent(tmp_path, raw):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=5,
        env={**os.environ, "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_hook_is_scoped_and_time_bounded():
    config = json.loads((ROOT / "hooks/hooks.json").read_text())
    entries = [
        entry
        for entry in config["hooks"]["SessionStart"]
        if any(
            "codex-session-recovery.py" in hook.get("command", "")
            for hook in entry["hooks"]
        )
    ]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "resume|compact"
    assert entries[0]["hooks"][0]["timeout"] <= 5


@pytest.mark.parametrize("source", ["resume", "compact"])
def test_cli_emits_session_context(context, source):
    payload, env = context
    payload["source"] = source
    job(env, pid=None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        env={**os.environ, **env},
    )
    assert result.returncode == 0 and result.stderr == ""
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "Monitor(" in output["additionalContext"]


def test_alarm_is_not_swallowed_by_state_reader(recovery, context, monkeypatch):
    payload, env = context
    path = job(env)
    monkeypatch.setattr(recovery.Path, "stat", recovery._timeout)
    with pytest.raises(recovery.DeadlineExpired):
        recovery.read_json(path)


def test_cli_exits_successfully_with_stdin_held_open(tmp_path):
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
    )
    try:
        assert process.wait(timeout=4.5) == 0
        assert process.stdout.read() == process.stderr.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_orphan_output_is_bounded(recovery, context, monkeypatch):
    payload, env = context
    for index in range(20):
        job(env, id=f"job-{index}")
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    output = recovery.recovery_context(payload, env)
    assert output.count("Codex orphan job=") == 5
    assert "+15 more orphaned jobs" in output


@pytest.mark.parametrize("location", ["plugin", "temporary"])
def test_launcher_state_root_variants(recovery, context, monkeypatch, location):
    payload, env = context
    path = job(env)
    if location == "plugin":
        root = Path(env["CLAUDE_PLUGIN_DATA"]) / "state"
    else:
        root = Path(env["TMPDIR"]) / "codex-companion"
    target = root / "workspace/jobs/orphan.json"
    target.parent.mkdir(parents=True)
    path.rename(target)
    monkeypatch.setattr(recovery, "pid_alive", lambda _: False)
    assert "orphan" in recovery.recovery_context(payload, env)


def test_monitor_uses_codex_store_instead_of_hook_plugin_data(recovery, context):
    payload, env = context
    job(env, pid=None)
    output = recovery.recovery_context(payload, env)
    assert (
        "CLAUDE_PLUGIN_DATA="
        + str(Path(env["HOME"]) / ".claude/plugins/data/codex-openai-codex")
        in output
    )
    assert env["CLAUDE_PLUGIN_DATA"] not in output
