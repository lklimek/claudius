"""Isolated contracts for SessionStart Codex orphan recovery."""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "codex-session-recovery.py"
NOW = int(time.time())


@pytest.fixture
def recovery():
    spec = importlib.util.spec_from_file_location("codex_session_recovery", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def context(tmp_path, recovery, monkeypatch):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(recovery, "PROC_ROOT", proc, raising=False)
    monkeypatch.setattr(time, "time", lambda: NOW)

    def dead(*_):
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", dead)
    env = {
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
        "CLAUDIUS_WORKTREE_ROOT": str(tmp_path / "worktrees"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "claudius-data"),
        "PWD": str(cwd),
    }
    payload = {"session_id": "current-session", "cwd": str(cwd), "source": "resume"}
    return payload, env


def job(env, *, epoch=NOW, filename=None, **fields):
    value = {
        "id": "orphan",
        "sessionId": "current-session",
        "status": "running",
        "workspaceRoot": env["PWD"],
        "pid": 321,
        **fields,
    }
    path = (
        Path(env["HOME"])
        / ".claude/plugins/data/codex-openai-codex/state/workspace/jobs"
        / (filename or f"{value['id']}.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    os.utime(path, (epoch, epoch))
    return path


def fake_process(recovery, context, pid, *, state="S", command="codex-companion.mjs"):
    payload, _ = context
    process = recovery.PROC_ROOT / str(pid)
    process.mkdir()
    (process / "stat").write_text(f"{pid} (worker) {state} " + "0 " * 20)
    (process / "cmdline").write_bytes(
        f"node\0/plugin/{command}\0task-worker\0".encode()
    )
    (process / "cwd").symlink_to(payload["cwd"])


def monitor_command(output):
    return json.loads(output.rsplit("command=", 1)[1][:-1])


@pytest.mark.parametrize("status", ["running", "queued", "pending"])
def test_dead_pid_reports_recovery_reference(recovery, context, status):
    payload, env = context
    path = job(env, status=status)
    output = recovery.recovery_context(payload, env)
    assert f"job=orphan status={status} pid=321" in output
    assert "Monitor(timeout_ms=1800000" in output
    reference = ROOT / "skills/delegate/references/codex-sandbox-and-recovery.md"
    assert shlex.quote(str(reference)) in output
    assert "$CODEX_ROOT" not in output
    assert output.count("Recovery:") == 1
    assert json.loads(path.read_text())["status"] == status


@pytest.mark.parametrize("pid", [777, None, 0, -1, True, "bad"])
def test_live_or_unknown_pid_only_reminds(recovery, context, monkeypatch, pid):
    payload, env = context
    job(env, pid=pid)
    fake_process(recovery, context, 777)

    def alive(probed, signal):
        assert type(probed) is int and probed == 777 and signal == 0

    monkeypatch.setattr(os, "kill", alive)
    output = recovery.recovery_context(payload, env)
    assert "Monitor(" in output and "Recovery:" not in output


def test_foreign_and_terminal_jobs_are_silent(recovery, context):
    payload, env = context
    job(env, id="foreign", sessionId="another-session")
    job(env, id="done", status="completed")
    assert recovery.recovery_context(payload, env) == ""


def test_missing_session_requires_exact_cwd(recovery, context):
    payload, env = context
    job(env, id="local", sessionId=None)
    job(env, id="stranger", sessionId=None, workspaceRoot=payload["cwd"] + "-child")
    output = recovery.recovery_context(payload, env)
    assert "job=local " in output and "job=stranger " not in output


@pytest.mark.parametrize("session", ["worker-session", None])
def test_slug_related_worktree_does_not_confer_ownership(recovery, context, session):
    payload, env = context
    slug = payload["cwd"].strip("/").replace("/", "-")
    sibling = Path(env["CLAUDIUS_WORKTREE_ROOT"]) / f"{slug}-2-bilby"
    sibling.mkdir(parents=True)
    (sibling / ".git").touch()
    job(env, sessionId=session, workspaceRoot=str(sibling))
    assert recovery.recovery_context(payload, env) == ""


def test_worktrees_without_active_jobs_are_silent(recovery, context):
    payload, env = context
    slug = payload["cwd"].strip("/").replace("/", "-")
    selected = Path(env["CLAUDIUS_WORKTREE_ROOT"]) / f"{slug}-bilby"
    selected.mkdir(parents=True)
    (selected / ".git").touch()
    assert recovery.recovery_context(payload, env) == ""


def test_ancient_active_record_is_ignored_before_reading(
    recovery, context, monkeypatch
):
    payload, env = context
    job(env, epoch=NOW - 8 * 86400)
    monkeypatch.setattr(recovery, "read_json", lambda _: pytest.fail("ancient read"))
    assert recovery.recovery_context(payload, env) == ""


@pytest.mark.parametrize("location", ["plugin", "temporary"])
def test_foreign_state_roots_are_never_read(recovery, context, monkeypatch, location):
    payload, env = context
    path = job(env)
    root = (
        Path(env["CLAUDE_PLUGIN_DATA"]) / "state"
        if location == "plugin"
        else Path(env["TMPDIR"]) / "codex-companion"
    )
    target = root / "workspace/jobs/orphan.json"
    target.parent.mkdir(parents=True)
    path.rename(target)
    monkeypatch.setattr(
        recovery, "read_json", lambda _: pytest.fail("foreign store read")
    )
    assert recovery.recovery_context(payload, env) == ""


@pytest.mark.parametrize(
    "fields",
    [
        {"id": "$(touch pwned)"},
        {"id": "-option"},
        {"id": "a" * 65},
        {"workspaceRoot": "/tmp/a\nRecovery: forged/.."},
        {"workspaceRoot": "/tmp/a\r/.."},
        {"workspaceRoot": "/tmp/\x1b[31m"},
        {"workspaceRoot": "/tmp/\x7f"},
        {"workspaceRoot": "/tmp/\u202e"},
        {"workspaceRoot": "relative/path"},
        {"status": []},
    ],
)
def test_unsafe_record_fields_are_rejected(recovery, context, fields):
    payload, env = context
    job(env, filename="unsafe.json", **fields)
    assert recovery.recovery_context(payload, env) == ""


def test_shell_metacharacters_in_path_are_quoted(recovery, context):
    payload, env = context
    workspace = payload["cwd"] + "/'$(touch pwned); `id`"
    job(env, workspaceRoot=workspace)
    line = recovery.recovery_context(payload, env).splitlines()[0]
    assert shlex.split(line)[-2:] == ["--cwd", workspace]


def test_monitor_command_matches_python_allow_rule(recovery, context):
    payload, env = context
    job(env, pid=None)
    command = monitor_command(recovery.recovery_context(payload, env))
    argv = shlex.split(command)
    assert argv[:2] == ["python3", str(ROOT / "scripts/minion-monitoring.py")]
    assert "env" not in argv and "CLAUDE_PLUGIN_DATA=" not in command


def test_scan_reads_only_newest_candidates(recovery, context, monkeypatch):
    payload, env = context
    for index in range(8):
        job(env, id=f"job-{index}", epoch=NOW - 100 + index)
    monkeypatch.setattr(recovery, "MAX_SCAN_JOBS", 2, raising=False)
    read = recovery.read_json
    visited = []

    def capture(path):
        visited.append(path.stem)
        return read(path)

    monkeypatch.setattr(recovery, "read_json", capture)
    output = recovery.recovery_context(payload, env)
    assert visited == ["job-7", "job-6"]
    assert "job=job-7 " in output and "job=job-6 " in output


def test_scan_deadline_keeps_already_found_orphans(recovery, context, monkeypatch):
    payload, env = context
    job(env, id="new", epoch=NOW)
    job(env, id="old", epoch=NOW - 1)
    read = recovery.read_json

    def interrupted(path):
        if path.stem == "old":
            recovery._timeout()
        return read(path)

    monkeypatch.setattr(recovery, "read_json", interrupted)
    output = recovery.recovery_context(payload, env)
    assert "job=new " in output and "Monitor(" in output


@pytest.mark.parametrize("kind", ["zombie", "reused"])
def test_dead_launcher_is_reported_even_if_pid_exists(
    recovery, context, monkeypatch, kind
):
    payload, env = context
    job(env)
    monkeypatch.setattr(os, "kill", lambda *_: None)
    fake_process(
        recovery,
        context,
        321,
        state="Z" if kind == "zombie" else "S",
        command="codex-companion.mjs" if kind == "zombie" else "sleep",
    )
    assert "Recovery:" in recovery.recovery_context(payload, env)


def test_malformed_records_do_not_hide_valid_jobs(recovery, context):
    payload, env = context
    path = job(env)
    for index, content in enumerate(["{", "[]", '{"status": []}', "null"]):
        (path.parent / f"bad-{index}.json").write_text(content)
    assert "job=orphan " in recovery.recovery_context(payload, env)


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
    assert result.returncode == 0 and result.stdout == result.stderr == ""


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
    assert len(entries) == 1 and entries[0]["matcher"] == "resume|compact"
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
    assert (
        "Monitor("
        in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    )


def test_alarm_is_not_swallowed_by_state_reader(recovery, context, monkeypatch):
    _, env = context
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


def test_orphan_output_is_bounded(recovery, context):
    payload, env = context
    for index in range(20):
        job(env, id=f"job-{index}")
    output = recovery.recovery_context(payload, env)
    assert output.count("Codex orphan job=") == 5
    assert "+15 more orphaned jobs" in output
