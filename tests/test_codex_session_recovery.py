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
    monkeypatch.setattr(os, "getppid", lambda: 101)
    for pid, parent, argv in ((100, 1, b"/opt/claude\0"), (101, 100, b"bash\0hook\0")):
        process = proc / str(pid)
        process.mkdir()
        (process / "stat").write_text(f"{pid} (process) S {parent} " + "0 " * 19)
        (process / "cmdline").write_bytes(argv)

    env = {
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "home/.claude"),
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
        Path(env.get("CLAUDE_CONFIG_DIR") or Path(env["HOME"]) / ".claude")
        / "plugins/data/codex-openai-codex/state/workspace/jobs"
        / (filename or f"{value['id']}.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    os.utime(path, (epoch, epoch))
    return path


def fake_process(
    recovery, context, pid, *, state="S", command="codex-companion.mjs", parent=100
):
    payload, _ = context
    process = recovery.PROC_ROOT / str(pid)
    process.mkdir()
    (process / "stat").write_text(f"{pid} (worker) {state} {parent} " + "0 " * 19)
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
def test_live_or_unknown_pid_only_reminds(recovery, context, pid):
    payload, env = context
    job(env, pid=pid)
    fake_process(recovery, context, 777)

    output = recovery.recovery_context(payload, env)
    assert "Monitor(" in output and "Recovery:" not in output


def test_foreign_and_terminal_jobs_are_silent(recovery, context):
    payload, env = context
    job(env, id="foreign", sessionId="another-session")
    job(env, id="done", status="completed", epoch=NOW - 7 * 3600)
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
def test_dead_or_reused_launcher_is_reported_even_if_pid_exists(
    recovery, context, kind
):
    payload, env = context
    job(env)
    fake_process(
        recovery,
        context,
        321,
        state="Z" if kind == "zombie" else "S",
        command="codex-companion.mjs" if kind == "zombie" else "sleep",
    )
    output = recovery.recovery_context(payload, env)
    if kind == "zombie":
        assert "Recovery:" in output
    else:
        assert "pid reused" in output and "inspect, do not cancel" in output
        assert "Recovery:" not in output


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


@pytest.mark.parametrize("outcome", ["alive", "absent", "denied"])
def test_missing_proc_uses_only_a_mocked_pid_probe(
    recovery, context, monkeypatch, outcome
):
    payload, env = context
    job(env)
    monkeypatch.setattr(recovery, "PROC_ROOT", recovery.PROC_ROOT / "missing")
    calls = []

    def probe(pid, signal):
        calls.append((pid, signal))
        if outcome == "absent":
            raise ProcessLookupError
        if outcome == "denied":
            raise PermissionError

    monkeypatch.setattr(os, "kill", probe)
    output = recovery.recovery_context(payload, env)
    assert calls == [(321, 0)]
    assert ("Recovery:" in output) == (outcome == "absent")


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_worktree_root_uses_default(recovery, context, value):
    payload, env = context
    env["CLAUDIUS_WORKTREE_ROOT"] = value
    job(env)
    output = recovery.recovery_context(payload, env)
    assert "job=orphan " in output
    assert shlex.split(monitor_command(output))[-1] == "/data/git-worktrees"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "canceled"])
def test_terminal_job_from_ninety_minute_outage_is_reported(recovery, context, status):
    payload, env = context
    job(env, id="finished", status=status, epoch=NOW - 5400, completedAt=NOW - 5400)
    job(env, id="foreign", status=status, sessionId="foreign-session")
    job(env, id="ancient", status=status, completedAt=NOW - 6 * 3600 - 1)
    output = recovery.recovery_context(payload, env)
    assert (
        "job=finished " in output
        and "job=foreign " not in output
        and "job=ancient " not in output
    )
    assert "--dump-job finished" in output
    assert "Monitor(" not in output and "Recovery:" not in output


def test_finished_job_output_is_bounded(recovery, context):
    payload, env = context
    for index in range(12):
        job(env, id=f"done-{index}", status="completed", completedAt=NOW - 5400)
    output = recovery.recovery_context(payload, env)
    assert output.count("Codex finished job=") == 5


@pytest.mark.parametrize(
    "monitor_session,state",
    [
        ("current-session", "S"),
        ("foreign-session", "S"),
        ("current-session", "Z"),
    ],
)
def test_surviving_watchdog_suppresses_only_its_session_reminder(
    recovery, context, monitor_session, state
):
    payload, env = context
    job(env)
    fake_process(recovery, context, 999, command="minion-monitoring.py", state=state)
    (recovery.PROC_ROOT / "999/cmdline").write_bytes(
        f"python3\0/plugin/scripts/minion-monitoring.py\0--session-id\0{monitor_session}\0".encode()
    )
    output = recovery.recovery_context(payload, env)
    assert "job=orphan " in output and "Recovery:" in output
    assert ("Monitor(" in output) == (
        monitor_session != "current-session" or state == "Z"
    )


def test_config_dir_relocates_hook_store(recovery, context):
    payload, env = context
    env["CLAUDE_CONFIG_DIR"] = str(Path(env["HOME"]) / "custom-config")
    job(env)
    assert "job=orphan " in recovery.recovery_context(payload, env)


def test_printed_monitor_does_not_filter_other_checkout_worktrees(recovery, context):
    payload, env = context
    job(env, workspaceRoot="/other/checkout/worktree")
    command = monitor_command(recovery.recovery_context(payload, env))
    assert "--worktrees-session-filter" not in command


def test_live_job_with_surviving_watchdog_is_silent(recovery, context):
    payload, env = context
    job(env, pid=777)
    fake_process(recovery, context, 777)
    fake_process(recovery, context, 999, command="minion-monitoring.py")
    (recovery.PROC_ROOT / "999/cmdline").write_bytes(
        b"python3\0/plugin/scripts/minion-monitoring.py\0--session-id\0current-session\0"
    )
    assert recovery.recovery_context(payload, env) == ""


def test_reused_pid_never_receives_the_orphan_recovery_advice(recovery, context):
    payload, env = context
    job(env, id="reused", pid=777)
    job(env, id="dead", pid=321)
    fake_process(recovery, context, 777, command="sleep")
    output = recovery.recovery_context(payload, env)
    reused = next(line for line in output.splitlines() if "job=reused " in line)
    assert "inspect, do not cancel" in reused
    assert "Recovery: for absent/zombie PIDs only" in output


def test_unreadable_watchdog_state_keeps_reminder(recovery, context):
    payload, env = context
    job(env)
    fake_process(recovery, context, 999, command="minion-monitoring.py")
    (recovery.PROC_ROOT / "999/cmdline").write_bytes(
        b"python3\0/plugin/scripts/minion-monitoring.py\0--session-id\0current-session\0"
    )
    (recovery.PROC_ROOT / "999/stat").unlink()
    assert "Monitor(" in recovery.recovery_context(payload, env)


@pytest.mark.parametrize(
    "completed", [float("nan"), float("inf"), 10**400], ids=["nan", "inf", "overflow"]
)
def test_invalid_completion_clock_does_not_hide_orphans(recovery, context, completed):
    payload, env = context
    job(env, id="dead")
    job(env, id="finished", status="completed", completedAt=completed)
    assert "job=dead " in recovery.recovery_context(payload, env)


def watchdog_process(recovery, context, *, argv=None, parent=100):
    fake_process(recovery, context, 999, command="minion-monitoring.py", parent=parent)
    arguments = argv or [
        "python3",
        "/plugin/scripts/minion-monitoring.py",
        "--session-id",
        "current-session",
    ]
    (recovery.PROC_ROOT / "999/cmdline").write_bytes(
        "\0".join(arguments).encode() + b"\0"
    )


def test_finished_jobs_are_silent_while_this_claude_watchdog_runs(recovery, context):
    payload, env = context
    job(env, id="finished", status="completed", completedAt=NOW - 5400)
    watchdog_process(recovery, context)
    assert recovery.recovery_context(payload, env) == ""


def test_truncated_finished_jobs_report_the_remaining_count(recovery, context):
    payload, env = context
    for index in range(12):
        job(env, id=f"done-{index}", status="completed", completedAt=NOW - 5400)
    output = recovery.recovery_context(payload, env)
    assert output.count("Codex finished job=") == 5
    assert "+7 more finished jobs" in output


@pytest.mark.parametrize(
    "case", ["argument", "other-user", "orphan", "other-claude", "shell"]
)
def test_unrelated_watchdog_lookalike_never_suppresses_reminder(
    recovery, context, monkeypatch, case
):
    payload, env = context
    job(env)
    parent = 1 if case == "orphan" else 100
    argv = (
        [
            "python3",
            "-c",
            "pass",
            "minion-monitoring.py",
            "--session-id",
            "current-session",
        ]
        if case == "argument"
        else None
    )
    if case == "shell":
        argv = [
            "bash",
            "/plugin/scripts/minion-monitoring.py",
            "--session-id",
            "current-session",
        ]
    if case == "other-claude":
        fake_process(recovery, context, 200, command="unused", parent=1)
        (recovery.PROC_ROOT / "200/cmdline").write_bytes(b"claude\0")
        parent = 200
    watchdog_process(recovery, context, argv=argv, parent=parent)
    if case == "other-user":
        original_stat = Path.stat

        def changed_owner(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            if path == recovery.PROC_ROOT / "999":
                from types import SimpleNamespace

                return SimpleNamespace(st_uid=os.getuid() + 1)
            return value

        monkeypatch.setattr(Path, "stat", changed_owner)
    assert "Monitor(" in recovery.recovery_context(payload, env)


def test_watchdog_descendant_through_shell_suppresses_reminder(recovery, context):
    payload, env = context
    job(env, pid=777)
    fake_process(recovery, context, 777)
    fake_process(recovery, context, 102, command="unused", parent=100)
    (recovery.PROC_ROOT / "102/cmdline").write_bytes(b"bash\0")
    watchdog_process(recovery, context, parent=102)
    assert recovery.recovery_context(payload, env) == ""


def test_pid_exit_mid_scan_does_not_hide_current_watchdog(
    recovery, context, monkeypatch
):
    payload, env = context
    job(env, pid=777)
    fake_process(recovery, context, 777)
    watchdog_process(recovery, context)
    gone = recovery.PROC_ROOT / "998"
    gone.mkdir()
    original_iterdir = Path.iterdir
    original_stat = Path.stat

    def ordered(path):
        if path == recovery.PROC_ROOT:
            return iter([gone, recovery.PROC_ROOT / "999"])
        return original_iterdir(path)

    def vanished(path, *args, **kwargs):
        if path == gone:
            raise FileNotFoundError
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", ordered)
    monkeypatch.setattr(Path, "stat", vanished)
    assert recovery.recovery_context(payload, env) == ""


def test_versioned_claude_ancestor_is_recognised(recovery, context):
    payload, env = context
    job(env, pid=777)
    fake_process(recovery, context, 777)
    watchdog_process(recovery, context)
    (recovery.PROC_ROOT / "100/cmdline").write_bytes(
        b"/home/user/.local/share/claude/versions/2.1.330\0"
    )
    assert recovery.recovery_context(payload, env) == ""


@pytest.mark.parametrize("path_kind", ["symlink", "trailing-slash"])
def test_hook_sessionless_jobs_use_canonical_cwd(recovery, context, path_kind):
    payload, env = context
    job(env, sessionId=None)
    alias = Path(env["HOME"]).parent / "alias"
    alias.symlink_to(payload["cwd"], target_is_directory=True)
    payload["cwd"] = str(alias) if path_kind == "symlink" else payload["cwd"] + "/"
    assert "job=orphan " in recovery.recovery_context(payload, env)


def test_finished_job_is_reported_once_across_resume_and_compact(recovery, context):
    payload, env = context
    job(env, id="finished", status="completed", completedAt=NOW - 5400)
    assert "job=finished " in recovery.recovery_context(payload, env)
    payload["source"] = "compact"
    assert recovery.recovery_context(payload, env) == ""
    payload["source"] = "resume"
    assert recovery.recovery_context(payload, env) == ""


def test_truncated_finished_jobs_are_reported_on_later_hooks_once_each(
    recovery, context
):
    payload, env = context
    for index in range(12):
        job(env, id=f"done-{index}", status="completed", completedAt=NOW - 5400)
    outputs = [recovery.recovery_context(payload, env) for _ in range(4)]
    assert [out.count("Codex finished job=") for out in outputs] == [5, 5, 2, 0]
    assert "+7 more finished jobs" in outputs[0]
    assert "+2 more finished jobs" in outputs[1]


def test_concurrent_hooks_report_each_finished_job_at_most_once(recovery, context):
    from concurrent.futures import ThreadPoolExecutor

    payload, env = context
    job(env, id="finished", status="completed", completedAt=NOW - 5400)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(
            executor.map(lambda _: recovery.recovery_context(payload, env), range(2))
        )
    assert sum(out.count("Codex finished job=") for out in outputs) == 1
